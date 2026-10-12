"""
Control Plane Policy Store.

Provides persistent storage for control plane policies (agent restrictions,
region constraints, SLA requirements) separate from compliance policies.

Supports SQLite (development) and PostgreSQL (production) backends.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from aragora.persistence.db_config import get_default_data_dir
from aragora.observability import get_logger
from aragora.storage.backends import POSTGRESQL_AVAILABLE, PostgreSQLBackend
from aragora.storage.base_store import SQLiteStore

from .policy import ControlPlanePolicy, PolicyViolation


class ControlPlanePolicyStoreProtocol(Protocol):
    """Protocol defining the interface for control plane policy stores.

    Both SQLite and PostgreSQL backends implement this interface.
    """

    def create_policy(self, policy: ControlPlanePolicy) -> ControlPlanePolicy:
        """Create a new control plane policy."""
        ...

    def get_policy(self, policy_id: str) -> ControlPlanePolicy | None:
        """Get a policy by ID."""
        ...

    def list_policies(
        self,
        enabled_only: bool = False,
        workspace: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ControlPlanePolicy]:
        """List policies with optional filters."""
        ...

    def update_policy(
        self,
        policy_id: str,
        updates: dict[str, Any],
    ) -> ControlPlanePolicy | None:
        """Update a policy."""
        ...

    def delete_policy(self, policy_id: str) -> bool:
        """Delete a policy."""
        ...

    def toggle_policy(self, policy_id: str, enabled: bool) -> bool:
        """Enable or disable a policy."""
        ...

    def create_violation(self, violation: PolicyViolation) -> PolicyViolation:
        """Record a policy violation."""
        ...

    def list_violations(
        self,
        policy_id: str | None = None,
        violation_type: str | None = None,
        status: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List violations with optional filters."""
        ...

    def count_violations(
        self,
        status: str | None = None,
        policy_id: str | None = None,
    ) -> dict[str, int]:
        """Count violations by type."""
        ...

    def update_violation_status(
        self,
        violation_id: str,
        status: str,
        resolved_by: str | None = None,
        resolution_notes: str | None = None,
    ) -> bool:
        """Update violation status."""
        ...


logger = get_logger(__name__)


def _get_default_db_path() -> Path:
    """Get the default database path for control plane policy store."""
    path = get_default_data_dir() / "control_plane" / "policies.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class ControlPlanePolicyStore(SQLiteStore):
    """
    SQLite-backed store for control plane policies.

    Stores:
    - ControlPlanePolicy configurations
    - PolicyViolation records with status tracking
    """

    SCHEMA_NAME = "control_plane_policy_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS control_plane_policies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            scope TEXT DEFAULT 'global',
            task_types TEXT DEFAULT '[]',
            capabilities TEXT DEFAULT '[]',
            workspaces TEXT DEFAULT '[]',
            agent_allowlist TEXT DEFAULT '[]',
            agent_blocklist TEXT DEFAULT '[]',
            region_constraint TEXT,
            sla TEXT,
            enforcement_level TEXT DEFAULT 'hard',
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            created_by TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS control_plane_violations (
            id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            violation_type TEXT NOT NULL,
            description TEXT NOT NULL,
            task_id TEXT,
            task_type TEXT,
            agent_id TEXT,
            region TEXT,
            workspace_id TEXT,
            enforcement_level TEXT DEFAULT 'hard',
            timestamp TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            resolved_at TEXT,
            resolved_by TEXT,
            resolution_notes TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_cp_policies_enabled ON control_plane_policies(enabled);
        CREATE INDEX IF NOT EXISTS idx_cp_violations_policy ON control_plane_violations(policy_id);
        CREATE INDEX IF NOT EXISTS idx_cp_violations_status ON control_plane_violations(status);
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize the policy store."""
        self.db_path = db_path or _get_default_db_path()

        # SECURITY: Check production guards for SQLite usage
        try:
            from aragora.storage.production_guards import (
                require_distributed_store,
                StorageMode,
            )

            require_distributed_store(
                "control_plane_policy_store",
                StorageMode.SQLITE,
                "Control plane policy store using SQLite - use PostgreSQL for multi-instance deployments",
            )
        except ImportError:
            pass  # Guards not available, allow SQLite

        super().__init__(str(self.db_path))

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a SQL statement and return the cursor.

        Args:
            sql: SQL statement to execute
            params: Parameters for the SQL statement

        Returns:
            sqlite3.Cursor with the results
        """
        return self._manager.execute(sql, params)

    def create_policy(self, policy: ControlPlanePolicy) -> ControlPlanePolicy:
        """Create a new control plane policy."""
        self.execute(
            """
            INSERT INTO control_plane_policies
            (id, name, description, scope, task_types, capabilities, workspaces,
             agent_allowlist, agent_blocklist, region_constraint, sla,
             enforcement_level, enabled, priority, created_at, created_by, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.id,
                policy.name,
                policy.description,
                policy.scope.value,
                json.dumps(policy.task_types),
                json.dumps(policy.capabilities),
                json.dumps(policy.workspaces),
                json.dumps(policy.agent_allowlist),
                json.dumps(policy.agent_blocklist),
                (
                    json.dumps(policy.region_constraint.to_dict())
                    if policy.region_constraint
                    else None
                ),
                json.dumps(policy.sla.to_dict()) if policy.sla else None,
                policy.enforcement_level.value,
                1 if policy.enabled else 0,
                policy.priority,
                policy.created_at.isoformat(),
                policy.created_by,
                json.dumps(policy.metadata),
            ),
        )
        logger.info("control_plane_policy_created", policy_id=policy.id, name=policy.name)
        return policy

    def get_policy(self, policy_id: str) -> ControlPlanePolicy | None:
        """Get a policy by ID."""
        row = self.execute(
            "SELECT * FROM control_plane_policies WHERE id = ?",
            (policy_id,),
        ).fetchone()
        if row:
            return self._row_to_policy(row)
        return None

    def list_policies(
        self,
        enabled_only: bool = False,
        workspace: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ControlPlanePolicy]:
        """List policies with optional filters."""
        query = "SELECT * FROM control_plane_policies WHERE 1=1"
        params: list[Any] = []

        if enabled_only:
            query += " AND enabled = 1"

        query += " ORDER BY priority DESC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.execute(query, tuple(params)).fetchall()
        policies = [self._row_to_policy(row) for row in rows]

        # Filter by workspace in Python (JSON array contains)
        if workspace:
            policies = [p for p in policies if not p.workspaces or workspace in p.workspaces]

        return policies

    def update_policy(
        self,
        policy_id: str,
        updates: dict[str, Any],
    ) -> ControlPlanePolicy | None:
        """Update a policy."""
        policy = self.get_policy(policy_id)
        if not policy:
            return None

        # Build update query dynamically
        set_clauses = []
        params = []

        field_mapping = {
            "name": "name",
            "description": "description",
            "enabled": "enabled",
            "priority": "priority",
            "enforcement_level": "enforcement_level",
        }

        for key, column in field_mapping.items():
            if key in updates:
                set_clauses.append(f"{column} = ?")
                value = updates[key]
                if key == "enabled":
                    value = 1 if value else 0
                elif key == "enforcement_level":
                    value = value.value if hasattr(value, "value") else value
                params.append(value)

        # JSON fields
        json_fields = [
            "task_types",
            "capabilities",
            "workspaces",
            "agent_allowlist",
            "agent_blocklist",
            "metadata",
        ]
        for field in json_fields:
            if field in updates:
                set_clauses.append(f"{field} = ?")
                params.append(json.dumps(updates[field]))

        # Nested objects
        if "region_constraint" in updates:
            set_clauses.append("region_constraint = ?")
            rc = updates["region_constraint"]
            params.append(json.dumps(rc.to_dict()) if rc else None)

        if "sla" in updates:
            set_clauses.append("sla = ?")
            sla = updates["sla"]
            params.append(json.dumps(sla.to_dict()) if sla else None)

        if not set_clauses:
            return policy

        params.append(policy_id)
        self.execute(
            # dynamic clause from internal state
            f"UPDATE control_plane_policies SET {', '.join(set_clauses)} WHERE id = ?",
            tuple(params),
        )

        logger.info("control_plane_policy_updated", policy_id=policy_id)
        return self.get_policy(policy_id)

    def delete_policy(self, policy_id: str) -> bool:
        """Delete a policy."""
        cursor = self.execute(
            "DELETE FROM control_plane_policies WHERE id = ?",
            (policy_id,),
        )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("control_plane_policy_deleted", policy_id=policy_id)
        return deleted

    def toggle_policy(self, policy_id: str, enabled: bool) -> bool:
        """Enable or disable a policy."""
        cursor = self.execute(
            "UPDATE control_plane_policies SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, policy_id),
        )
        return cursor.rowcount > 0

    def create_violation(self, violation: PolicyViolation) -> PolicyViolation:
        """Record a policy violation."""
        self.execute(
            """
            INSERT INTO control_plane_violations
            (id, policy_id, policy_name, violation_type, description,
             task_id, task_type, agent_id, region, workspace_id,
             enforcement_level, timestamp, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                violation.id,
                violation.policy_id,
                violation.policy_name,
                violation.violation_type,
                violation.description,
                violation.task_id,
                violation.task_type,
                violation.agent_id,
                violation.region,
                violation.workspace_id,
                violation.enforcement_level.value,
                violation.timestamp.isoformat(),
                "open",
                json.dumps(violation.metadata),
            ),
        )
        logger.info(
            "control_plane_violation_recorded",
            violation_id=violation.id,
            policy_id=violation.policy_id,
            type=violation.violation_type,
        )
        return violation

    def list_violations(
        self,
        policy_id: str | None = None,
        violation_type: str | None = None,
        status: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List violations with optional filters."""
        query = "SELECT * FROM control_plane_violations WHERE 1=1"
        params: list[Any] = []

        if policy_id:
            query += " AND policy_id = ?"
            params.append(policy_id)

        if violation_type:
            query += " AND violation_type = ?"
            params.append(violation_type)

        if status:
            query += " AND status = ?"
            params.append(status)

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.execute(query, tuple(params)).fetchall()
        return [self._row_to_violation_dict(row) for row in rows]

    def count_violations(
        self,
        status: str | None = None,
        policy_id: str | None = None,
    ) -> dict[str, int]:
        """Count violations by type."""
        query = """
            SELECT violation_type, COUNT(*) as count
            FROM control_plane_violations
            WHERE 1=1
        """
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)

        if policy_id:
            query += " AND policy_id = ?"
            params.append(policy_id)

        query += " GROUP BY violation_type"

        rows = self.execute(query, tuple(params)).fetchall()
        return {row["violation_type"]: row["count"] for row in rows}

    def update_violation_status(
        self,
        violation_id: str,
        status: str,
        resolved_by: str | None = None,
        resolution_notes: str | None = None,
    ) -> bool:
        """Update violation status."""
        resolved_at = datetime.now(timezone.utc).isoformat() if status == "resolved" else None
        cursor = self.execute(
            """
            UPDATE control_plane_violations
            SET status = ?, resolved_at = ?, resolved_by = ?, resolution_notes = ?
            WHERE id = ?
            """,
            (status, resolved_at, resolved_by, resolution_notes, violation_id),
        )
        return cursor.rowcount > 0

    def _row_to_policy(self, row: Any) -> ControlPlanePolicy:
        """Convert a database row to a ControlPlanePolicy."""
        return ControlPlanePolicy.from_dict(
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "scope": row["scope"],
                "task_types": json.loads(row["task_types"]) if row["task_types"] else [],
                "capabilities": json.loads(row["capabilities"]) if row["capabilities"] else [],
                "workspaces": json.loads(row["workspaces"]) if row["workspaces"] else [],
                "agent_allowlist": (
                    json.loads(row["agent_allowlist"]) if row["agent_allowlist"] else []
                ),
                "agent_blocklist": (
                    json.loads(row["agent_blocklist"]) if row["agent_blocklist"] else []
                ),
                "region_constraint": (
                    json.loads(row["region_constraint"]) if row["region_constraint"] else None
                ),
                "sla": json.loads(row["sla"]) if row["sla"] else None,
                "enforcement_level": row["enforcement_level"],
                "enabled": bool(row["enabled"]),
                "priority": row["priority"],
                "created_at": row["created_at"],
                "created_by": row["created_by"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            }
        )

    def _row_to_violation_dict(self, row: Any) -> dict[str, Any]:
        """Convert a database row to a violation dict."""
        return {
            "id": row["id"],
            "policy_id": row["policy_id"],
            "policy_name": row["policy_name"],
            "violation_type": row["violation_type"],
            "description": row["description"],
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "agent_id": row["agent_id"],
            "region": row["region"],
            "workspace_id": row["workspace_id"],
            "enforcement_level": row["enforcement_level"],
            "timestamp": row["timestamp"],
            "status": row["status"],
            "resolved_at": row["resolved_at"],
            "resolved_by": row["resolved_by"],
            "resolution_notes": row["resolution_notes"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }


class PostgresControlPlanePolicyStore:
    """PostgreSQL-backed store for control plane policies (production)."""

    def __init__(self, backend: PostgreSQLBackend):
        """Initialize with PostgreSQL backend."""
        self._backend = backend
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self._backend.execute_write("""
            CREATE TABLE IF NOT EXISTS control_plane_policies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                scope TEXT DEFAULT 'global',
                task_types JSONB DEFAULT '[]',
                capabilities JSONB DEFAULT '[]',
                workspaces JSONB DEFAULT '[]',
                agent_allowlist JSONB DEFAULT '[]',
                agent_blocklist JSONB DEFAULT '[]',
                region_constraint JSONB,
                sla JSONB,
                enforcement_level TEXT DEFAULT 'hard',
                enabled BOOLEAN DEFAULT TRUE,
                priority INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_by TEXT,
                metadata JSONB DEFAULT '{}'
            )
            """)
        self._backend.execute_write("""
            CREATE TABLE IF NOT EXISTS control_plane_violations (
                id TEXT PRIMARY KEY,
                policy_id TEXT NOT NULL,
                policy_name TEXT NOT NULL,
                violation_type TEXT NOT NULL,
                description TEXT NOT NULL,
                task_id TEXT,
                task_type TEXT,
                agent_id TEXT,
                region TEXT,
                workspace_id TEXT,
                enforcement_level TEXT DEFAULT 'hard',
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status TEXT DEFAULT 'open',
                resolved_at TIMESTAMPTZ,
                resolved_by TEXT,
                resolution_notes TEXT,
                metadata JSONB DEFAULT '{}'
            )
            """)
        self._backend.execute_write(
            "CREATE INDEX IF NOT EXISTS idx_cp_pg_policies_enabled ON control_plane_policies(enabled)"
        )
        self._backend.execute_write(
            "CREATE INDEX IF NOT EXISTS idx_cp_pg_violations_status ON control_plane_violations(status)"
        )

    def create_policy(self, policy: ControlPlanePolicy) -> ControlPlanePolicy:
        """Create a new control plane policy."""
        import json as json_module

        self._backend.execute_write(
            """
            INSERT INTO control_plane_policies
            (id, name, description, scope, task_types, capabilities, workspaces,
             agent_allowlist, agent_blocklist, region_constraint, sla,
             enforcement_level, enabled, priority, created_at, created_by, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            """,
            (
                policy.id,
                policy.name,
                policy.description,
                policy.scope.value,
                json_module.dumps(policy.task_types),
                json_module.dumps(policy.capabilities),
                json_module.dumps(policy.workspaces),
                json_module.dumps(policy.agent_allowlist),
                json_module.dumps(policy.agent_blocklist),
                (
                    json_module.dumps(policy.region_constraint.to_dict())
                    if policy.region_constraint
                    else None
                ),
                json_module.dumps(policy.sla.to_dict()) if policy.sla else None,
                policy.enforcement_level.value,
                policy.enabled,
                policy.priority,
                policy.created_at.isoformat(),
                policy.created_by,
                json_module.dumps(policy.metadata),
            ),
        )
        logger.info("control_plane_policy_created", policy_id=policy.id, name=policy.name)
        return policy

    def get_policy(self, policy_id: str) -> ControlPlanePolicy | None:
        """Get a policy by ID."""
        rows = self._backend.execute_read(
            "SELECT * FROM control_plane_policies WHERE id = $1",
            (policy_id,),
        )
        if rows:
            return self._row_to_policy(rows[0])
        return None

    def list_policies(
        self,
        enabled_only: bool = False,
        workspace: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ControlPlanePolicy]:
        """List policies with optional filters."""
        query = "SELECT * FROM control_plane_policies WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if enabled_only:
            query += " AND enabled = TRUE"

        query += (
            f" ORDER BY priority DESC, created_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        )
        params.extend([limit, offset])

        rows = self._backend.execute_read(query, tuple(params))
        policies = [self._row_to_policy(row) for row in rows]

        # Filter by workspace in Python (JSONB array contains)
        if workspace:
            policies = [p for p in policies if not p.workspaces or workspace in p.workspaces]

        return policies

    def update_policy(
        self,
        policy_id: str,
        updates: dict[str, Any],
    ) -> ControlPlanePolicy | None:
        """Update a policy."""
        import json as json_module

        policy = self.get_policy(policy_id)
        if not policy:
            return None

        # Build update query dynamically
        set_clauses = []
        params = []
        param_idx = 1

        field_mapping = {
            "name": "name",
            "description": "description",
            "enabled": "enabled",
            "priority": "priority",
            "enforcement_level": "enforcement_level",
        }

        for key, column in field_mapping.items():
            if key in updates:
                set_clauses.append(f"{column} = ${param_idx}")
                value = updates[key]
                if key == "enforcement_level":
                    value = value.value if hasattr(value, "value") else value
                params.append(value)
                param_idx += 1

        # JSON fields
        json_fields = [
            "task_types",
            "capabilities",
            "workspaces",
            "agent_allowlist",
            "agent_blocklist",
            "metadata",
        ]
        for field in json_fields:
            if field in updates:
                set_clauses.append(f"{field} = ${param_idx}")
                params.append(json_module.dumps(updates[field]))
                param_idx += 1

        # Nested objects
        if "region_constraint" in updates:
            set_clauses.append(f"region_constraint = ${param_idx}")
            rc = updates["region_constraint"]
            params.append(json_module.dumps(rc.to_dict()) if rc else None)
            param_idx += 1

        if "sla" in updates:
            set_clauses.append(f"sla = ${param_idx}")
            sla = updates["sla"]
            params.append(json_module.dumps(sla.to_dict()) if sla else None)
            param_idx += 1

        if not set_clauses:
            return policy

        params.append(policy_id)
        self._backend.execute_write(
            # dynamic clause from internal state
            f"UPDATE control_plane_policies SET {', '.join(set_clauses)} WHERE id = ${param_idx}",
            tuple(params),
        )

        logger.info("control_plane_policy_updated", policy_id=policy_id)
        return self.get_policy(policy_id)

    def delete_policy(self, policy_id: str) -> bool:
        """Delete a policy."""
        self._backend.execute_write(
            "DELETE FROM control_plane_policies WHERE id = $1",
            (policy_id,),
        )
        # execute_write doesn't return a value, assume success if no exception
        logger.info("control_plane_policy_deleted", policy_id=policy_id)
        return True

    def toggle_policy(self, policy_id: str, enabled: bool) -> bool:
        """Enable or disable a policy."""
        self._backend.execute_write(
            "UPDATE control_plane_policies SET enabled = $1 WHERE id = $2",
            (enabled, policy_id),
        )
        return True  # execute_write doesn't return a value

    def create_violation(self, violation: PolicyViolation) -> PolicyViolation:
        """Record a policy violation."""
        import json as json_module

        self._backend.execute_write(
            """
            INSERT INTO control_plane_violations
            (id, policy_id, policy_name, violation_type, description,
             task_id, task_type, agent_id, region, workspace_id,
             enforcement_level, timestamp, status, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
            (
                violation.id,
                violation.policy_id,
                violation.policy_name,
                violation.violation_type,
                violation.description,
                violation.task_id,
                violation.task_type,
                violation.agent_id,
                violation.region,
                violation.workspace_id,
                violation.enforcement_level.value,
                violation.timestamp.isoformat(),
                "open",
                json_module.dumps(violation.metadata),
            ),
        )
        logger.info(
            "control_plane_violation_recorded",
            violation_id=violation.id,
            policy_id=violation.policy_id,
            type=violation.violation_type,
        )
        return violation

    def list_violations(
        self,
        policy_id: str | None = None,
        violation_type: str | None = None,
        status: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List violations with optional filters."""
        query = "SELECT * FROM control_plane_violations WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if policy_id:
            query += f" AND policy_id = ${param_idx}"
            params.append(policy_id)
            param_idx += 1

        if violation_type:
            query += f" AND violation_type = ${param_idx}"
            params.append(violation_type)
            param_idx += 1

        if status:
            query += f" AND status = ${param_idx}"
            params.append(status)
            param_idx += 1

        if workspace_id:
            query += f" AND workspace_id = ${param_idx}"
            params.append(workspace_id)
            param_idx += 1

        query += f" ORDER BY timestamp DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        rows = self._backend.execute_read(query, tuple(params))
        return [self._row_to_violation_dict(row) for row in rows]

    def count_violations(
        self,
        status: str | None = None,
        policy_id: str | None = None,
    ) -> dict[str, int]:
        """Count violations by type."""
        query = """
            SELECT violation_type, COUNT(*) as count
            FROM control_plane_violations
            WHERE 1=1
        """
        params: list[Any] = []
        param_idx = 1

        if status:
            query += f" AND status = ${param_idx}"
            params.append(status)
            param_idx += 1

        if policy_id:
            query += f" AND policy_id = ${param_idx}"
            params.append(policy_id)
            param_idx += 1

        query += " GROUP BY violation_type"

        rows = self._backend.execute_read(query, tuple(params))
        return {row["violation_type"]: row["count"] for row in rows}

    def update_violation_status(
        self,
        violation_id: str,
        status: str,
        resolved_by: str | None = None,
        resolution_notes: str | None = None,
    ) -> bool:
        """Update violation status."""
        resolved_at = datetime.now(timezone.utc).isoformat() if status == "resolved" else None
        self._backend.execute_write(
            """
            UPDATE control_plane_violations
            SET status = $1, resolved_at = $2, resolved_by = $3, resolution_notes = $4
            WHERE id = $5
            """,
            (status, resolved_at, resolved_by, resolution_notes, violation_id),
        )
        return True  # execute_write doesn't return a value

    def _row_to_policy(self, row: Any) -> ControlPlanePolicy:
        """Convert a database row to a ControlPlanePolicy."""
        return ControlPlanePolicy.from_dict(
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "scope": row["scope"],
                "task_types": row["task_types"] if isinstance(row["task_types"], list) else [],
                "capabilities": (
                    row["capabilities"] if isinstance(row["capabilities"], list) else []
                ),
                "workspaces": row["workspaces"] if isinstance(row["workspaces"], list) else [],
                "agent_allowlist": (
                    row["agent_allowlist"] if isinstance(row["agent_allowlist"], list) else []
                ),
                "agent_blocklist": (
                    row["agent_blocklist"] if isinstance(row["agent_blocklist"], list) else []
                ),
                "region_constraint": row["region_constraint"] if row["region_constraint"] else None,
                "sla": row["sla"] if row["sla"] else None,
                "enforcement_level": row["enforcement_level"],
                "enabled": bool(row["enabled"]),
                "priority": row["priority"],
                "created_at": (
                    row["created_at"].isoformat()
                    if hasattr(row["created_at"], "isoformat")
                    else row["created_at"]
                ),
                "created_by": row["created_by"],
                "metadata": row["metadata"] if isinstance(row["metadata"], dict) else {},
            }
        )

    def _row_to_violation_dict(self, row: Any) -> dict[str, Any]:
        """Convert a database row to a violation dict."""
        return {
            "id": row["id"],
            "policy_id": row["policy_id"],
            "policy_name": row["policy_name"],
            "violation_type": row["violation_type"],
            "description": row["description"],
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "agent_id": row["agent_id"],
            "region": row["region"],
            "workspace_id": row["workspace_id"],
            "enforcement_level": row["enforcement_level"],
            "timestamp": (
                row["timestamp"].isoformat()
                if hasattr(row["timestamp"], "isoformat")
                else row["timestamp"]
            ),
            "status": row["status"],
            "resolved_at": (
                row["resolved_at"].isoformat()
                if row["resolved_at"] and hasattr(row["resolved_at"], "isoformat")
                else row["resolved_at"]
            ),
            "resolved_by": row["resolved_by"],
            "resolution_notes": row["resolution_notes"],
            "metadata": row["metadata"] if isinstance(row["metadata"], dict) else {},
        }


# Factory function
_policy_store_instance: ControlPlanePolicyStoreProtocol | None = None


def get_control_plane_policy_store(
    db_path: Path | None = None,
) -> ControlPlanePolicyStoreProtocol:
    """
    Get or create the control plane policy store singleton.

    Uses ARAGORA_CONTROL_PLANE_POLICY_STORE_BACKEND env var to select backend.
    Defaults to SQLite for development, PostgreSQL for production.
    """
    global _policy_store_instance

    if _policy_store_instance is not None:
        return _policy_store_instance

    backend = os.environ.get("ARAGORA_CONTROL_PLANE_POLICY_STORE_BACKEND", "sqlite")

    if backend == "postgres" and POSTGRESQL_AVAILABLE:
        pg_url = os.environ.get("ARAGORA_POSTGRES_URL") or os.environ.get("DATABASE_URL")
        if pg_url:
            logger.info("Using PostgreSQL backend for control plane policy store")
            try:
                pg_backend = PostgreSQLBackend(pg_url)
                # Use a wrapper that matches SQLite store interface
                _policy_store_instance = PostgresControlPlanePolicyStore(pg_backend)
                logger.info("control_plane_policy_store_initialized", backend="postgres")
                return _policy_store_instance
            except (
                RuntimeError,
                ValueError,
                OSError,
                ConnectionError,
                TimeoutError,
                ImportError,
            ) as e:
                logger.warning(
                    "Failed to initialize PostgreSQL policy store: %s, falling back to SQLite", e
                )

    _policy_store_instance = ControlPlanePolicyStore(db_path)
    logger.info(
        "control_plane_policy_store_initialized",
        backend="sqlite",
        path=str(db_path or _get_default_db_path()),
    )
    return _policy_store_instance


def reset_control_plane_policy_store() -> None:
    """Reset the policy store singleton (for testing)."""
    global _policy_store_instance
    _policy_store_instance = None
