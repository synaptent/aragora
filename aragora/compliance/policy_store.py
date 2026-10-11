"""
Policy Store for managing compliance policies and violations.

Provides persistent storage for:
- Policy configurations (enabled frameworks, rules, thresholds)
- Compliance violations (detected issues with status tracking)
- Audit trail of policy changes
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.persistence.db_config import get_default_data_dir
from aragora.storage.backends import POSTGRESQL_AVAILABLE, PostgreSQLBackend
from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    """Get the default database path for policy store."""
    path = get_default_data_dir() / "compliance" / "policy_store.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class PolicyRule:
    """A rule within a policy."""

    rule_id: str
    name: str
    description: str
    severity: str  # critical, high, medium, low
    enabled: bool = True
    custom_threshold: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "enabled": self.enabled,
            "custom_threshold": self.custom_threshold,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyRule:
        return cls(
            rule_id=data["rule_id"],
            name=data["name"],
            description=data.get("description", ""),
            severity=data.get("severity", "medium"),
            enabled=data.get("enabled", True),
            custom_threshold=data.get("custom_threshold"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Policy:
    """A compliance policy configuration."""

    id: str
    name: str
    description: str
    framework_id: str  # Maps to ComplianceFramework from framework.py
    workspace_id: str
    vertical_id: str
    level: str = "recommended"  # mandatory, recommended, optional
    enabled: bool = True
    rules: list[PolicyRule] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "framework_id": self.framework_id,
            "workspace_id": self.workspace_id,
            "vertical_id": self.vertical_id,
            "level": self.level,
            "enabled": self.enabled,
            "rules": [r.to_dict() for r in self.rules],
            "rules_count": len(self.rules),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        rules = [PolicyRule.from_dict(r) for r in data.get("rules", [])]
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now(timezone.utc)

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            framework_id=data["framework_id"],
            workspace_id=data.get("workspace_id", "default"),
            vertical_id=data.get("vertical_id", ""),
            level=data.get("level", "recommended"),
            enabled=data.get("enabled", True),
            rules=rules,
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Violation:
    """A compliance violation."""

    id: str
    policy_id: str
    rule_id: str
    rule_name: str
    framework_id: str
    vertical_id: str
    workspace_id: str
    severity: str  # critical, high, medium, low
    status: str  # open, investigating, resolved, false_positive
    description: str
    source: str  # File/location where violation was detected
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "framework_id": self.framework_id,
            "vertical_id": self.vertical_id,
            "workspace_id": self.workspace_id,
            "severity": self.severity,
            "status": self.status,
            "description": self.description,
            "source": self.source,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_notes": self.resolution_notes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Violation:
        detected_at = data.get("detected_at")
        if isinstance(detected_at, str):
            detected_at = datetime.fromisoformat(detected_at)
        elif detected_at is None:
            detected_at = datetime.now(timezone.utc)

        resolved_at = data.get("resolved_at")
        if isinstance(resolved_at, str):
            resolved_at = datetime.fromisoformat(resolved_at)

        return cls(
            id=data["id"],
            policy_id=data.get("policy_id", ""),
            rule_id=data["rule_id"],
            rule_name=data.get("rule_name", ""),
            framework_id=data["framework_id"],
            vertical_id=data.get("vertical_id", ""),
            workspace_id=data.get("workspace_id", "default"),
            severity=data.get("severity", "medium"),
            status=data.get("status", "open"),
            description=data.get("description", ""),
            source=data.get("source", ""),
            detected_at=detected_at,
            resolved_at=resolved_at,
            resolved_by=data.get("resolved_by"),
            resolution_notes=data.get("resolution_notes"),
            metadata=data.get("metadata", {}),
        )


def _parse_datetime(value: Any, fallback: datetime | None = None) -> datetime:
    """Parse datetime from string or datetime, with fallback."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Failed to parse datetime string: %s", value)
            return fallback or datetime.now(timezone.utc)
    if value is not None:
        logger.debug("Unexpected datetime value type %s, using fallback", type(value).__name__)
    return fallback or datetime.now(timezone.utc)


def _parse_optional_datetime(value: Any) -> datetime | None:
    """Parse optional datetime from string or datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Failed to parse optional datetime string: %s", value)
            return None
    logger.debug("Unexpected optional datetime value type %s, returning None", type(value).__name__)
    return None


class PolicyStore(SQLiteStore):
    """
    SQLite-backed store for compliance policies and violations.

    Provides:
    - CRUD operations for policies
    - Violation tracking with status management
    - Filtering by workspace, vertical, framework, and status
    - Audit trail for policy changes
    """

    SCHEMA_NAME = "policy_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Policies table
        CREATE TABLE IF NOT EXISTS policies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            framework_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT 'default',
            vertical_id TEXT NOT NULL,
            level TEXT DEFAULT 'recommended',
            enabled INTEGER DEFAULT 1,
            rules_json TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_policies_workspace ON policies(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_policies_framework ON policies(framework_id);
        CREATE INDEX IF NOT EXISTS idx_policies_vertical ON policies(vertical_id);

        -- Violations table
        CREATE TABLE IF NOT EXISTS violations (
            id TEXT PRIMARY KEY,
            policy_id TEXT,
            rule_id TEXT NOT NULL,
            rule_name TEXT,
            framework_id TEXT NOT NULL,
            vertical_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT 'default',
            severity TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open',
            description TEXT,
            source TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            resolved_by TEXT,
            resolution_notes TEXT,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_violations_workspace ON violations(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_violations_framework ON violations(framework_id);
        CREATE INDEX IF NOT EXISTS idx_violations_status ON violations(status);
        CREATE INDEX IF NOT EXISTS idx_violations_severity ON violations(severity);
        CREATE INDEX IF NOT EXISTS idx_violations_policy ON violations(policy_id);

        -- Policy audit log
        CREATE TABLE IF NOT EXISTS policy_audit (
            id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL,
            action TEXT NOT NULL,
            changed_by TEXT,
            changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            old_value TEXT,
            new_value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_policy ON policy_audit(policy_id);
    """

    def __init__(self, db_path: Path | None = None):
        super().__init__(db_path or _get_default_db_path())

    # =========================================================================
    # Policy CRUD
    # =========================================================================

    def create_policy(self, policy: Policy) -> Policy:
        """Create a new policy."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO policies (
                    id, name, description, framework_id, workspace_id, vertical_id,
                    level, enabled, rules_json, created_at, updated_at, created_by, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.id,
                    policy.name,
                    policy.description,
                    policy.framework_id,
                    policy.workspace_id,
                    policy.vertical_id,
                    policy.level,
                    1 if policy.enabled else 0,
                    json.dumps([r.to_dict() for r in policy.rules]),
                    policy.created_at.isoformat(),
                    policy.updated_at.isoformat(),
                    policy.created_by,
                    json.dumps(policy.metadata),
                ),
            )
            self._log_audit(conn, policy.id, "create", None, policy.to_dict(), policy.created_by)
        return policy

    def get_policy(self, policy_id: str) -> Policy | None:
        """Get a policy by ID."""
        row = self.fetch_one("SELECT * FROM policies WHERE id = ?", (policy_id,))
        if not row:
            return None
        return self._row_to_policy(row)

    def list_policies(
        self,
        workspace_id: str | None = None,
        vertical_id: str | None = None,
        framework_id: str | None = None,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Policy]:
        """List policies with optional filters."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if vertical_id:
            conditions.append("vertical_id = ?")
            params.append(vertical_id)
        if framework_id:
            conditions.append("framework_id = ?")
            params.append(framework_id)
        if enabled_only:
            conditions.append("enabled = 1")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # internal query construction
        sql = f"SELECT * FROM policies {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.fetch_all(sql, tuple(params))
        return [self._row_to_policy(row) for row in rows]

    def update_policy(
        self,
        policy_id: str,
        updates: dict[str, Any],
        changed_by: str | None = None,
    ) -> Policy | None:
        """Update a policy."""
        current = self.get_policy(policy_id)
        if not current:
            return None

        old_value = current.to_dict()

        # Apply updates
        if "name" in updates:
            current.name = updates["name"]
        if "description" in updates:
            current.description = updates["description"]
        if "level" in updates:
            current.level = updates["level"]
        if "enabled" in updates:
            current.enabled = updates["enabled"]
        if "rules" in updates:
            current.rules = [PolicyRule.from_dict(r) for r in updates["rules"]]
        if "metadata" in updates:
            current.metadata.update(updates["metadata"])

        current.updated_at = datetime.now(timezone.utc)

        with self.connection() as conn:
            conn.execute(
                """
                UPDATE policies SET
                    name = ?, description = ?, level = ?, enabled = ?,
                    rules_json = ?, updated_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    current.name,
                    current.description,
                    current.level,
                    1 if current.enabled else 0,
                    json.dumps([r.to_dict() for r in current.rules]),
                    current.updated_at.isoformat(),
                    json.dumps(current.metadata),
                    policy_id,
                ),
            )
            self._log_audit(conn, policy_id, "update", old_value, current.to_dict(), changed_by)

        return current

    def delete_policy(self, policy_id: str, deleted_by: str | None = None) -> bool:
        """Delete a policy."""
        policy = self.get_policy(policy_id)
        if not policy:
            return False

        with self.connection() as conn:
            self._log_audit(conn, policy_id, "delete", policy.to_dict(), None, deleted_by)
            conn.execute("DELETE FROM policies WHERE id = ?", (policy_id,))
        return True

    def toggle_policy(self, policy_id: str, enabled: bool, changed_by: str | None = None) -> bool:
        """Toggle policy enabled status."""
        result = self.update_policy(policy_id, {"enabled": enabled}, changed_by)
        return result is not None

    # =========================================================================
    # Violation CRUD
    # =========================================================================

    def create_violation(self, violation: Violation) -> Violation:
        """Create a new violation."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO violations (
                    id, policy_id, rule_id, rule_name, framework_id, vertical_id,
                    workspace_id, severity, status, description, source,
                    detected_at, resolved_at, resolved_by, resolution_notes, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    violation.id,
                    violation.policy_id,
                    violation.rule_id,
                    violation.rule_name,
                    violation.framework_id,
                    violation.vertical_id,
                    violation.workspace_id,
                    violation.severity,
                    violation.status,
                    violation.description,
                    violation.source,
                    violation.detected_at.isoformat(),
                    violation.resolved_at.isoformat() if violation.resolved_at else None,
                    violation.resolved_by,
                    violation.resolution_notes,
                    json.dumps(violation.metadata),
                ),
            )
        return violation

    def get_violation(self, violation_id: str) -> Violation | None:
        """Get a violation by ID."""
        row = self.fetch_one("SELECT * FROM violations WHERE id = ?", (violation_id,))
        if not row:
            return None
        return self._row_to_violation(row)

    def list_violations(
        self,
        workspace_id: str | None = None,
        vertical_id: str | None = None,
        framework_id: str | None = None,
        policy_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Violation]:
        """List violations with optional filters."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if vertical_id:
            conditions.append("vertical_id = ?")
            params.append(vertical_id)
        if framework_id:
            conditions.append("framework_id = ?")
            params.append(framework_id)
        if policy_id:
            conditions.append("policy_id = ?")
            params.append(policy_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # internal query construction
        sql = f"SELECT * FROM violations {where} ORDER BY detected_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.fetch_all(sql, tuple(params))
        return [self._row_to_violation(row) for row in rows]

    def update_violation_status(
        self,
        violation_id: str,
        status: str,
        resolved_by: str | None = None,
        resolution_notes: str | None = None,
    ) -> Violation | None:
        """Update a violation's status."""
        violation = self.get_violation(violation_id)
        if not violation:
            return None

        resolved_at = None
        if status in ("resolved", "false_positive"):
            resolved_at = datetime.now(timezone.utc)

        with self.connection() as conn:
            conn.execute(
                """
                UPDATE violations SET status = ?, resolved_at = ?, resolved_by = ?, resolution_notes = ?
                WHERE id = ?
                """,
                (
                    status,
                    resolved_at.isoformat() if resolved_at else None,
                    resolved_by,
                    resolution_notes,
                    violation_id,
                ),
            )

        violation.status = status
        violation.resolved_at = resolved_at
        violation.resolved_by = resolved_by
        violation.resolution_notes = resolution_notes
        return violation

    def delete_violation(self, violation_id: str) -> bool:
        """Delete a violation."""
        return self.delete_by_id("violations", "id", violation_id)

    def count_violations(
        self,
        workspace_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
    ) -> dict[str, int]:
        """Get violation counts by severity."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT severity, COUNT(*) as count FROM violations {where}
            GROUP BY severity
        """  # internal query construction

        rows = self.fetch_all(sql, tuple(params))
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
        for row in rows:
            severity_val = row[0]
            count_val = row[1]
            if severity_val in counts:
                counts[severity_val] = count_val
            counts["total"] += count_val
        return counts

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_policy(self, row: tuple) -> Policy:
        """Convert database row to Policy object."""
        # Column order: id, name, description, framework_id, workspace_id, vertical_id,
        #              level, enabled, rules_json, created_at, updated_at, created_by, metadata_json
        return Policy(
            id=row[0],
            name=row[1],
            description=row[2] or "",
            framework_id=row[3],
            workspace_id=row[4],
            vertical_id=row[5],
            level=row[6] or "recommended",
            enabled=bool(row[7]),
            rules=[PolicyRule.from_dict(r) for r in json.loads(row[8] or "[]")],
            created_at=_parse_datetime(row[9]),
            updated_at=_parse_datetime(row[10]),
            created_by=row[11],
            metadata=json.loads(row[12] or "{}"),
        )

    def _row_to_violation(self, row: tuple) -> Violation:
        """Convert database row to Violation object."""
        # Column order: id, policy_id, rule_id, rule_name, framework_id, vertical_id,
        #              workspace_id, severity, status, description, source,
        #              detected_at, resolved_at, resolved_by, resolution_notes, metadata_json
        return Violation(
            id=row[0],
            policy_id=row[1] or "",
            rule_id=row[2],
            rule_name=row[3] or "",
            framework_id=row[4],
            vertical_id=row[5],
            workspace_id=row[6],
            severity=row[7] or "medium",
            status=row[8] or "open",
            description=row[9] or "",
            source=row[10] or "",
            detected_at=_parse_datetime(row[11]),
            resolved_at=_parse_optional_datetime(row[12]),
            resolved_by=row[13],
            resolution_notes=row[14],
            metadata=json.loads(row[15] or "{}"),
        )

    def _log_audit(
        self,
        conn,
        policy_id: str,
        action: str,
        old_value: dict | None,
        new_value: dict | None,
        changed_by: str | None,
    ) -> None:
        """Log a policy change to the audit table."""
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO policy_audit (id, policy_id, action, changed_by, old_value, new_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                policy_id,
                action,
                changed_by,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
            ),
        )


# =============================================================================
# PostgreSQL Backend
# =============================================================================


class PostgresPolicyStore:
    """
    PostgreSQL-backed store for compliance policies and violations.

    Provides the same API as PolicyStore, with a production-grade backend
    suitable for multi-instance deployments.
    """

    def __init__(self, database_url: str):
        if not POSTGRESQL_AVAILABLE:
            raise ImportError("psycopg2 required for PostgreSQL policy store")
        self._backend = PostgreSQLBackend(database_url)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        for statement in PolicyStore.INITIAL_SCHEMA.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                self._backend.execute_write(stmt)

    def _execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a write operation."""
        self._backend.execute_write(sql, params)

    def _fetch_one(self, sql: str, params: tuple = ()) -> tuple | None:
        """Execute a query and return one row."""
        return self._backend.fetch_one(sql, params)

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Execute a query and return all rows."""
        return self._backend.fetch_all(sql, params)

    # =========================================================================
    # Policy CRUD
    # =========================================================================

    def create_policy(self, policy: Policy) -> Policy:
        """Create a new policy."""
        self._execute(
            """
            INSERT INTO policies (
                id, name, description, framework_id, workspace_id, vertical_id,
                level, enabled, rules_json, created_at, updated_at, created_by, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.id,
                policy.name,
                policy.description,
                policy.framework_id,
                policy.workspace_id,
                policy.vertical_id,
                policy.level,
                1 if policy.enabled else 0,
                json.dumps([r.to_dict() for r in policy.rules]),
                policy.created_at.isoformat(),
                policy.updated_at.isoformat(),
                policy.created_by,
                json.dumps(policy.metadata),
            ),
        )
        self._log_audit(policy.id, "create", None, policy.to_dict(), policy.created_by)
        return policy

    def get_policy(self, policy_id: str) -> Policy | None:
        """Get a policy by ID."""
        row = self._fetch_one("SELECT * FROM policies WHERE id = ?", (policy_id,))
        if not row:
            return None
        return self._row_to_policy(row)

    def list_policies(
        self,
        workspace_id: str | None = None,
        vertical_id: str | None = None,
        framework_id: str | None = None,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Policy]:
        """List policies with optional filters."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if vertical_id:
            conditions.append("vertical_id = ?")
            params.append(vertical_id)
        if framework_id:
            conditions.append("framework_id = ?")
            params.append(framework_id)
        if enabled_only:
            conditions.append("enabled = 1")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # internal query construction
        sql = f"SELECT * FROM policies {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._fetch_all(sql, tuple(params))
        return [self._row_to_policy(row) for row in rows]

    def update_policy(
        self,
        policy_id: str,
        updates: dict[str, Any],
        changed_by: str | None = None,
    ) -> Policy | None:
        """Update a policy."""
        current = self.get_policy(policy_id)
        if not current:
            return None

        old_value = current.to_dict()

        # Apply updates
        if "name" in updates:
            current.name = updates["name"]
        if "description" in updates:
            current.description = updates["description"]
        if "level" in updates:
            current.level = updates["level"]
        if "enabled" in updates:
            current.enabled = updates["enabled"]
        if "rules" in updates:
            current.rules = [PolicyRule.from_dict(r) for r in updates["rules"]]
        if "metadata" in updates:
            current.metadata.update(updates["metadata"])

        current.updated_at = datetime.now(timezone.utc)

        self._execute(
            """
            UPDATE policies SET
                name = ?, description = ?, level = ?, enabled = ?,
                rules_json = ?, updated_at = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                current.name,
                current.description,
                current.level,
                1 if current.enabled else 0,
                json.dumps([r.to_dict() for r in current.rules]),
                current.updated_at.isoformat(),
                json.dumps(current.metadata),
                policy_id,
            ),
        )
        self._log_audit(policy_id, "update", old_value, current.to_dict(), changed_by)

        return current

    def delete_policy(self, policy_id: str, deleted_by: str | None = None) -> bool:
        """Delete a policy."""
        policy = self.get_policy(policy_id)
        if not policy:
            return False

        self._log_audit(policy_id, "delete", policy.to_dict(), None, deleted_by)
        self._execute("DELETE FROM policies WHERE id = ?", (policy_id,))
        return True

    def toggle_policy(self, policy_id: str, enabled: bool, changed_by: str | None = None) -> bool:
        """Toggle policy enabled status."""
        result = self.update_policy(policy_id, {"enabled": enabled}, changed_by)
        return result is not None

    # =========================================================================
    # Violation CRUD
    # =========================================================================

    def create_violation(self, violation: Violation) -> Violation:
        """Create a new violation."""
        self._execute(
            """
            INSERT INTO violations (
                id, policy_id, rule_id, rule_name, framework_id, vertical_id,
                workspace_id, severity, status, description, source,
                detected_at, resolved_at, resolved_by, resolution_notes, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                violation.id,
                violation.policy_id,
                violation.rule_id,
                violation.rule_name,
                violation.framework_id,
                violation.vertical_id,
                violation.workspace_id,
                violation.severity,
                violation.status,
                violation.description,
                violation.source,
                violation.detected_at.isoformat(),
                violation.resolved_at.isoformat() if violation.resolved_at else None,
                violation.resolved_by,
                violation.resolution_notes,
                json.dumps(violation.metadata),
            ),
        )
        return violation

    def get_violation(self, violation_id: str) -> Violation | None:
        """Get a violation by ID."""
        row = self._fetch_one("SELECT * FROM violations WHERE id = ?", (violation_id,))
        if not row:
            return None
        return self._row_to_violation(row)

    def list_violations(
        self,
        workspace_id: str | None = None,
        vertical_id: str | None = None,
        framework_id: str | None = None,
        policy_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Violation]:
        """List violations with optional filters."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if vertical_id:
            conditions.append("vertical_id = ?")
            params.append(vertical_id)
        if framework_id:
            conditions.append("framework_id = ?")
            params.append(framework_id)
        if policy_id:
            conditions.append("policy_id = ?")
            params.append(policy_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # internal query construction
        sql = f"SELECT * FROM violations {where} ORDER BY detected_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._fetch_all(sql, tuple(params))
        return [self._row_to_violation(row) for row in rows]

    def update_violation_status(
        self,
        violation_id: str,
        status: str,
        resolved_by: str | None = None,
        resolution_notes: str | None = None,
    ) -> Violation | None:
        """Update a violation's status."""
        violation = self.get_violation(violation_id)
        if not violation:
            return None

        resolved_at = None
        if status in ("resolved", "false_positive"):
            resolved_at = datetime.now(timezone.utc)

        self._execute(
            """
            UPDATE violations SET status = ?, resolved_at = ?, resolved_by = ?, resolution_notes = ?
            WHERE id = ?
            """,
            (
                status,
                resolved_at.isoformat() if resolved_at else None,
                resolved_by,
                resolution_notes,
                violation_id,
            ),
        )

        violation.status = status
        violation.resolved_at = resolved_at
        violation.resolved_by = resolved_by
        violation.resolution_notes = resolution_notes
        return violation

    def delete_violation(self, violation_id: str) -> bool:
        """Delete a violation."""
        self._execute("DELETE FROM violations WHERE id = ?", (violation_id,))
        return True

    def count_violations(
        self,
        workspace_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
    ) -> dict[str, int]:
        """Get violation counts by severity."""
        conditions = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT severity, COUNT(*) as count FROM violations {where}
            GROUP BY severity
        """  # internal query construction

        rows = self._fetch_all(sql, tuple(params))
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
        for row in rows:
            severity_val = row[0]
            count_val = row[1]
            if severity_val in counts:
                counts[severity_val] = count_val
            counts["total"] += count_val
        return counts

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_policy(self, row: tuple) -> Policy:
        """Convert database row to Policy object."""
        return Policy(
            id=row[0],
            name=row[1],
            description=row[2] or "",
            framework_id=row[3],
            workspace_id=row[4],
            vertical_id=row[5],
            level=row[6] or "recommended",
            enabled=bool(row[7]),
            rules=[PolicyRule.from_dict(r) for r in json.loads(row[8] or "[]")],
            created_at=_parse_datetime(row[9]),
            updated_at=_parse_datetime(row[10]),
            created_by=row[11],
            metadata=json.loads(row[12] or "{}"),
        )

    def _row_to_violation(self, row: tuple) -> Violation:
        """Convert database row to Violation object."""
        return Violation(
            id=row[0],
            policy_id=row[1] or "",
            rule_id=row[2],
            rule_name=row[3] or "",
            framework_id=row[4],
            vertical_id=row[5],
            workspace_id=row[6],
            severity=row[7] or "medium",
            status=row[8] or "open",
            description=row[9] or "",
            source=row[10] or "",
            detected_at=_parse_datetime(row[11]),
            resolved_at=_parse_optional_datetime(row[12]),
            resolved_by=row[13],
            resolution_notes=row[14],
            metadata=json.loads(row[15] or "{}"),
        )

    def _log_audit(
        self,
        policy_id: str,
        action: str,
        old_value: dict | None,
        new_value: dict | None,
        changed_by: str | None,
    ) -> None:
        """Log a policy change to the audit table."""
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        self._execute(
            """
            INSERT INTO policy_audit (id, policy_id, action, changed_by, old_value, new_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                policy_id,
                action,
                changed_by,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
            ),
        )


# Singleton instance
_policy_store: PolicyStore | PostgresPolicyStore | None = None


def get_policy_store(db_path: Path | None = None) -> PolicyStore | PostgresPolicyStore:
    """Get or create the policy store singleton.

    Uses environment variables to configure:
    - ARAGORA_POLICY_STORE_BACKEND: "sqlite" or "postgres"
    - ARAGORA_DB_BACKEND: Fallback backend selection
    - ARAGORA_POSTGRES_DSN or DATABASE_URL: PostgreSQL connection string
    """
    global _policy_store
    if _policy_store is not None:
        return _policy_store

    backend_type = os.environ.get("ARAGORA_POLICY_STORE_BACKEND")
    if not backend_type:
        backend_type = os.environ.get("ARAGORA_DB_BACKEND", "sqlite")
    backend_type = backend_type.lower()

    database_url = (
        os.environ.get("ARAGORA_POSTGRES_DSN")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("ARAGORA_DATABASE_URL")
    )

    if backend_type in ("postgres", "postgresql"):
        if not database_url:
            logger.warning("PostgreSQL policy store selected but DATABASE_URL is missing")
        else:
            try:
                _policy_store = PostgresPolicyStore(database_url)
                return _policy_store
            except (ConnectionError, OSError, RuntimeError, ValueError) as e:
                logger.warning("PostgreSQL policy store unavailable, falling back to SQLite: %s", e)
                try:
                    from aragora.storage.production_guards import (
                        require_distributed_store,
                        StorageMode,
                    )

                    require_distributed_store(
                        "policy_store",
                        StorageMode.SQLITE,
                        f"PostgreSQL backend unavailable: {e}",
                    )
                except ImportError:
                    logger.debug(
                        "production_guards not available, skipping distributed store check"
                    )

    # Default: SQLite
    try:
        from aragora.storage.production_guards import require_distributed_store, StorageMode

        require_distributed_store(
            "policy_store",
            StorageMode.SQLITE,
            "Compliance policy store using SQLite - configure PostgreSQL for multi-instance deployments.",
        )
    except ImportError:
        logger.debug("production_guards not available, skipping distributed store check")

    _policy_store = PolicyStore(db_path)
    return _policy_store


__all__ = [
    "Policy",
    "PolicyRule",
    "Violation",
    "PolicyStore",
    "PostgresPolicyStore",
    "get_policy_store",
]
