"""
Governance Module for Knowledge Mound.

Provides enterprise governance features:
- Role-Based Access Control (RBAC)
- Audit trail logging
- Policy enforcement
- Compliance tracking

Phase A2 - Workspace Governance
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from aragora.config import resolve_db_path

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# =============================================================================
# Role-Based Access Control
# =============================================================================


class Permission(str, Enum):
    """Knowledge Mound permissions."""

    # Item permissions
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"

    # Workspace permissions
    MANAGE_WORKSPACE = "manage_workspace"
    SHARE = "share"
    EXPORT = "export"

    # Admin permissions
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    VIEW_AUDIT = "view_audit"
    MANAGE_POLICIES = "manage_policies"

    # System permissions
    ADMIN = "admin"  # Full access


class BuiltinRole(str, Enum):
    """Built-in role templates."""

    VIEWER = "viewer"  # Read-only access
    CONTRIBUTOR = "contributor"  # Read + create
    EDITOR = "editor"  # Read + create + update
    MANAGER = "manager"  # Full item access + sharing
    ADMIN = "admin"  # Full access including user management


@dataclass
class Role:
    """A role with associated permissions."""

    id: str
    name: str
    description: str
    permissions: set[Permission]
    workspace_id: str | None = None  # None = global role
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str | None = None
    is_builtin: bool = False

    def has_permission(self, permission: Permission) -> bool:
        """Check if role has a specific permission."""
        if Permission.ADMIN in self.permissions:
            return True
        return permission in self.permissions

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": [p.value for p in self.permissions],
            "workspace_id": self.workspace_id,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "is_builtin": self.is_builtin,
        }


@dataclass
class RoleAssignment:
    """Assignment of a role to a user."""

    id: str
    user_id: str
    role_id: str
    workspace_id: str | None = None  # None = global assignment
    assigned_at: datetime = field(default_factory=datetime.now)
    assigned_by: str | None = None
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        """Check if assignment has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "role_id": self.role_id,
            "workspace_id": self.workspace_id,
            "assigned_at": self.assigned_at.isoformat(),
            "assigned_by": self.assigned_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


# Built-in role definitions
BUILTIN_ROLES: dict[BuiltinRole, Role] = {
    BuiltinRole.VIEWER: Role(
        id="builtin:viewer",
        name="Viewer",
        description="Read-only access to knowledge items",
        permissions={Permission.READ},
        is_builtin=True,
    ),
    BuiltinRole.CONTRIBUTOR: Role(
        id="builtin:contributor",
        name="Contributor",
        description="Can read and create knowledge items",
        permissions={Permission.READ, Permission.CREATE},
        is_builtin=True,
    ),
    BuiltinRole.EDITOR: Role(
        id="builtin:editor",
        name="Editor",
        description="Can read, create, and update knowledge items",
        permissions={Permission.READ, Permission.CREATE, Permission.UPDATE},
        is_builtin=True,
    ),
    BuiltinRole.MANAGER: Role(
        id="builtin:manager",
        name="Manager",
        description="Full item access plus sharing and workspace management",
        permissions={
            Permission.READ,
            Permission.CREATE,
            Permission.UPDATE,
            Permission.DELETE,
            Permission.SHARE,
            Permission.EXPORT,
            Permission.MANAGE_WORKSPACE,
        },
        is_builtin=True,
    ),
    BuiltinRole.ADMIN: Role(
        id="builtin:admin",
        name="Administrator",
        description="Full access to all features",
        permissions={Permission.ADMIN},
        is_builtin=True,
    ),
}


class RBACManager:
    """Manages role-based access control."""

    def __init__(self):
        """Initialize RBAC manager."""
        self._roles: dict[str, Role] = {}
        self._assignments: dict[str, RoleAssignment] = {}
        self._user_roles: dict[str, set[str]] = {}  # user_id -> role_ids
        self._lock = asyncio.Lock()

        # Initialize builtin roles
        for role in BUILTIN_ROLES.values():
            self._roles[role.id] = role

    async def create_role(
        self,
        name: str,
        permissions: set[Permission],
        description: str = "",
        workspace_id: str | None = None,
        created_by: str | None = None,
    ) -> Role:
        """Create a new custom role.

        Args:
            name: Role name
            permissions: Set of permissions
            description: Role description
            workspace_id: Optional workspace scope
            created_by: User creating the role

        Returns:
            Created Role
        """
        import uuid

        role = Role(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            permissions=permissions,
            workspace_id=workspace_id,
            created_by=created_by,
        )

        async with self._lock:
            self._roles[role.id] = role

        logger.info("Created role: %s (%s)", role.name, role.id)
        return role

    async def assign_role(
        self,
        user_id: str,
        role_id: str,
        workspace_id: str | None = None,
        assigned_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> RoleAssignment:
        """Assign a role to a user.

        Args:
            user_id: User to assign role to
            role_id: Role to assign
            workspace_id: Optional workspace scope
            assigned_by: User making the assignment
            expires_at: Optional expiration

        Returns:
            RoleAssignment
        """
        import uuid

        async with self._lock:
            if role_id not in self._roles:
                raise ValueError(f"Role not found: {role_id}")

            assignment = RoleAssignment(
                id=str(uuid.uuid4()),
                user_id=user_id,
                role_id=role_id,
                workspace_id=workspace_id,
                assigned_by=assigned_by,
                expires_at=expires_at,
            )

            self._assignments[assignment.id] = assignment

            if user_id not in self._user_roles:
                self._user_roles[user_id] = set()
            self._user_roles[user_id].add(role_id)

        logger.info("Assigned role %s to user %s", role_id, user_id)
        return assignment

    async def revoke_role(
        self,
        user_id: str,
        role_id: str,
        workspace_id: str | None = None,
    ) -> bool:
        """Revoke a role from a user.

        Args:
            user_id: User to revoke from
            role_id: Role to revoke
            workspace_id: Optional workspace scope

        Returns:
            True if revoked, False if not found
        """
        async with self._lock:
            # Find matching assignment
            to_remove = None
            for aid, assignment in self._assignments.items():
                if (
                    assignment.user_id == user_id
                    and assignment.role_id == role_id
                    and assignment.workspace_id == workspace_id
                ):
                    to_remove = aid
                    break

            if to_remove:
                del self._assignments[to_remove]
                if user_id in self._user_roles:
                    self._user_roles[user_id].discard(role_id)
                logger.info("Revoked role %s from user %s", role_id, user_id)
                return True

            return False

    async def check_permission(
        self,
        user_id: str,
        permission: Permission,
        workspace_id: str | None = None,
    ) -> bool:
        """Check if user has a permission.

        Args:
            user_id: User to check
            permission: Permission to check
            workspace_id: Optional workspace context

        Returns:
            True if user has permission
        """
        async with self._lock:
            role_ids = self._user_roles.get(user_id, set())

            for role_id in role_ids:
                role = self._roles.get(role_id)
                if not role:
                    continue

                # Check workspace scope
                if workspace_id and role.workspace_id:
                    if role.workspace_id != workspace_id:
                        continue

                if role.has_permission(permission):
                    return True

            return False

    async def get_user_permissions(
        self,
        user_id: str,
        workspace_id: str | None = None,
    ) -> set[Permission]:
        """Get all permissions for a user.

        Args:
            user_id: User to get permissions for
            workspace_id: Optional workspace filter

        Returns:
            Set of permissions
        """
        permissions: set[Permission] = set()

        async with self._lock:
            role_ids = self._user_roles.get(user_id, set())

            for role_id in role_ids:
                role = self._roles.get(role_id)
                if not role:
                    continue

                if workspace_id and role.workspace_id:
                    if role.workspace_id != workspace_id:
                        continue

                if Permission.ADMIN in role.permissions:
                    return set(Permission)  # All permissions

                permissions.update(role.permissions)

        return permissions

    async def get_user_roles(
        self,
        user_id: str,
        workspace_id: str | None = None,
    ) -> list[Role]:
        """Get all roles for a user."""
        async with self._lock:
            role_ids = self._user_roles.get(user_id, set())
            roles = []

            for role_id in role_ids:
                role = self._roles.get(role_id)
                if role:
                    if workspace_id and role.workspace_id:
                        if role.workspace_id == workspace_id:
                            roles.append(role)
                    else:
                        roles.append(role)

            return roles


# =============================================================================
# Audit Trail
# =============================================================================


class AuditAction(str, Enum):
    """Auditable actions in Knowledge Mound."""

    # Item actions
    ITEM_CREATE = "item.create"
    ITEM_READ = "item.read"
    ITEM_UPDATE = "item.update"
    ITEM_DELETE = "item.delete"

    # Sharing actions
    SHARE_GRANT = "share.grant"
    SHARE_REVOKE = "share.revoke"

    # Admin actions
    ROLE_CREATE = "role.create"
    ROLE_ASSIGN = "role.assign"
    ROLE_REVOKE = "role.revoke"

    # Policy actions
    POLICY_CREATE = "policy.create"
    POLICY_UPDATE = "policy.update"
    POLICY_DELETE = "policy.delete"

    # System actions
    EXPORT = "export"
    IMPORT = "import"
    BULK_DELETE = "bulk_delete"


@dataclass
class AuditEntry:
    """An entry in the audit trail."""

    id: str
    action: AuditAction
    actor_id: str  # User who performed action
    resource_type: str  # Type of resource affected
    resource_id: str  # ID of resource affected
    workspace_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict[str, Any] = field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    success: bool = True
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "action": self.action.value,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "workspace_id": self.workspace_id,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "success": self.success,
            "error_message": self.error_message,
        }


class AuditTrail:
    """Manages audit trail logging with optional persistent storage."""

    def __init__(
        self,
        max_entries: int = 100000,
        enable_persistence: bool = True,
        db_path: str | None = None,
    ):
        """Initialize audit trail.

        Args:
            max_entries: Maximum entries to keep in memory
            enable_persistence: Enable SQLite persistence (default True)
            db_path: Optional custom database path
        """
        self._entries: list[AuditEntry] = []
        self._max_entries = max_entries
        self._lock = asyncio.Lock()
        self._enable_persistence = enable_persistence
        self._db_path = db_path
        self._db_initialized = False

    async def _ensure_db(self) -> None:
        """Initialize the database if persistence is enabled."""
        if not self._enable_persistence or self._db_initialized:
            return

        try:
            import aiosqlite
            from pathlib import Path

            # Default path in ARAGORA_DATA_DIR
            if self._db_path is None:
                self._db_path = resolve_db_path("km_audit.db")
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS audit_entries (
                        id TEXT PRIMARY KEY,
                        action TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        resource_type TEXT NOT NULL,
                        resource_id TEXT NOT NULL,
                        workspace_id TEXT,
                        timestamp REAL NOT NULL,
                        details TEXT,
                        ip_address TEXT,
                        user_agent TEXT,
                        success INTEGER NOT NULL DEFAULT 1,
                        error_message TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_entries(actor_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_entries(action)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_entries(timestamp DESC)
                """)
                await db.commit()

            self._db_initialized = True
            logger.debug("Initialized KM audit database at %s", self._db_path)
        except ImportError:
            logger.warning("aiosqlite not available, falling back to in-memory audit storage")
            self._enable_persistence = False
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to initialize audit database: %s", e)
            self._enable_persistence = False

    async def _persist_entry(self, entry: AuditEntry) -> None:
        """Persist an entry to the database."""
        if not self._enable_persistence:
            return

        await self._ensure_db()

        # Re-check after _ensure_db — it may have disabled persistence on ImportError
        if not self._enable_persistence:
            return

        try:
            import aiosqlite
            import json

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    INSERT INTO audit_entries
                    (id, action, actor_id, resource_type, resource_id, workspace_id,
                     timestamp, details, ip_address, user_agent, success, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        entry.id,
                        entry.action.value,
                        entry.actor_id,
                        entry.resource_type,
                        entry.resource_id,
                        entry.workspace_id,
                        entry.timestamp.timestamp(),
                        json.dumps(entry.details),
                        entry.ip_address,
                        entry.user_agent,
                        1 if entry.success else 0,
                        entry.error_message,
                    ),
                )
                await db.commit()
        except ImportError:
            logger.warning("aiosqlite not available, disabling persistence")
            self._enable_persistence = False
        except (ValueError, KeyError, TypeError, OSError) as e:
            logger.warning("Failed to persist audit entry: %s", e)

    async def log(
        self,
        action: AuditAction,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        workspace_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> AuditEntry:
        """Log an audit entry.

        Args:
            action: Action performed
            actor_id: User who performed action
            resource_type: Type of resource
            resource_id: ID of resource
            workspace_id: Optional workspace
            details: Additional details
            ip_address: Client IP
            user_agent: Client user agent
            success: Whether action succeeded
            error_message: Error if failed

        Returns:
            Created AuditEntry
        """
        import uuid

        entry = AuditEntry(
            id=str(uuid.uuid4()),
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
        )

        async with self._lock:
            self._entries.append(entry)

            # Trim if over limit
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]

        logger.debug("Audit: %s by %s on %s/%s", action.value, actor_id, resource_type, resource_id)

        # Persist to database asynchronously
        await self._persist_entry(entry)

        return entry

    async def query(
        self,
        actor_id: str | None = None,
        action: AuditAction | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        workspace_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        success_only: bool = False,
        limit: int = 100,
        offset: int = 0,
        from_database: bool = True,
    ) -> list[AuditEntry]:
        """Query audit entries.

        Args:
            actor_id: Filter by actor
            action: Filter by action
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            workspace_id: Filter by workspace
            start_time: Filter by start time
            end_time: Filter by end time
            success_only: Only successful actions
            limit: Maximum results
            offset: Result offset
            from_database: Query from database if persistence is enabled

        Returns:
            List of matching entries
        """
        # Try database query first if enabled
        if from_database and self._enable_persistence:
            db_results = await self._query_from_db(
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                workspace_id=workspace_id,
                start_time=start_time,
                end_time=end_time,
                success_only=success_only,
                limit=limit,
                offset=offset,
            )
            if db_results is not None:
                return db_results

        # Fall back to in-memory query
        async with self._lock:
            results = self._entries

            if actor_id:
                results = [e for e in results if e.actor_id == actor_id]

            if action:
                results = [e for e in results if e.action == action]

            if resource_type:
                results = [e for e in results if e.resource_type == resource_type]

            if resource_id:
                results = [e for e in results if e.resource_id == resource_id]

            if workspace_id:
                results = [e for e in results if e.workspace_id == workspace_id]

            if start_time:
                results = [e for e in results if e.timestamp >= start_time]

            if end_time:
                results = [e for e in results if e.timestamp <= end_time]

            if success_only:
                results = [e for e in results if e.success]

            # Sort by timestamp descending
            results = sorted(results, key=lambda e: e.timestamp, reverse=True)

            return results[offset : offset + limit]

    async def _query_from_db(
        self,
        actor_id: str | None = None,
        action: AuditAction | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        workspace_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        success_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry] | None:
        """Query entries from the database."""
        await self._ensure_db()
        if not self._db_initialized:
            return None

        try:
            import aiosqlite
            import json

            conditions = []
            params: list[Any] = []

            if actor_id:
                conditions.append("actor_id = ?")
                params.append(actor_id)
            if action:
                conditions.append("action = ?")
                params.append(action.value)
            if resource_type:
                conditions.append("resource_type = ?")
                params.append(resource_type)
            if resource_id:
                conditions.append("resource_id = ?")
                params.append(resource_id)
            if workspace_id:
                conditions.append("workspace_id = ?")
                params.append(workspace_id)
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(start_time.timestamp())
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(end_time.timestamp())
            if success_only:
                conditions.append("success = 1")

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            query = f"""
                SELECT id, action, actor_id, resource_type, resource_id,
                       workspace_id, timestamp, details, ip_address,
                       user_agent, success, error_message
                FROM audit_entries
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """  # dynamic clause from internal state
            params.extend([limit, offset])

            entries = []
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(query, params) as cursor:
                    async for row in cursor:
                        entry = AuditEntry(
                            id=row[0],
                            action=AuditAction(row[1]),
                            actor_id=row[2],
                            resource_type=row[3],
                            resource_id=row[4],
                            workspace_id=row[5],
                            timestamp=datetime.fromtimestamp(row[6]),
                            details=json.loads(row[7]) if row[7] else {},
                            ip_address=row[8],
                            user_agent=row[9],
                            success=bool(row[10]),
                            error_message=row[11],
                        )
                        entries.append(entry)

            return entries
        except ImportError:
            logger.warning("aiosqlite not available, disabling persistence")
            self._enable_persistence = False
            return None
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Database query failed, falling back to in-memory: %s", e)
            return None

    async def get_user_activity(
        self,
        user_id: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get activity summary for a user.

        Args:
            user_id: User to get activity for
            days: Number of days to look back

        Returns:
            Activity summary
        """
        from datetime import timedelta

        start_time = datetime.now() - timedelta(days=days)

        entries = await self.query(
            actor_id=user_id,
            start_time=start_time,
        )

        by_action: dict[str, int] = {}
        by_resource: dict[str, int] = {}

        for entry in entries:
            by_action[entry.action.value] = by_action.get(entry.action.value, 0) + 1
            by_resource[entry.resource_type] = by_resource.get(entry.resource_type, 0) + 1

        return {
            "user_id": user_id,
            "period_days": days,
            "total_actions": len(entries),
            "by_action": by_action,
            "by_resource": by_resource,
            "success_rate": sum(1 for e in entries if e.success) / len(entries) if entries else 1.0,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get audit trail statistics."""
        by_action: dict[str, int] = {}
        by_resource: dict[str, int] = {}
        failures = 0

        for entry in self._entries:
            by_action[entry.action.value] = by_action.get(entry.action.value, 0) + 1
            by_resource[entry.resource_type] = by_resource.get(entry.resource_type, 0) + 1
            if not entry.success:
                failures += 1

        return {
            "total_entries": len(self._entries),
            "by_action": by_action,
            "by_resource": by_resource,
            "failures": failures,
            "success_rate": (
                (len(self._entries) - failures) / len(self._entries) if self._entries else 1.0
            ),
        }


# =============================================================================
# Governance Mixin
# =============================================================================


class GovernanceMixin:
    """Mixin for governance operations on KnowledgeMound."""

    _rbac_manager: RBACManager | None = None
    _audit_trail: AuditTrail | None = None

    def _get_rbac_manager(self) -> RBACManager:
        """Get or create RBAC manager."""
        if self._rbac_manager is None:
            self._rbac_manager = RBACManager()
        return self._rbac_manager

    def _get_audit_trail(self) -> AuditTrail:
        """Get or create audit trail."""
        if self._audit_trail is None:
            self._audit_trail = AuditTrail()
        return self._audit_trail

    # RBAC methods
    async def create_role(
        self,
        name: str,
        permissions: set[Permission],
        description: str = "",
        workspace_id: str | None = None,
        created_by: str | None = None,
    ) -> Role:
        """Create a new role."""
        return await self._get_rbac_manager().create_role(
            name, permissions, description, workspace_id, created_by
        )

    async def assign_role(
        self,
        user_id: str,
        role_id: str,
        workspace_id: str | None = None,
        assigned_by: str | None = None,
    ) -> RoleAssignment:
        """Assign a role to a user."""
        return await self._get_rbac_manager().assign_role(
            user_id, role_id, workspace_id, assigned_by
        )

    async def revoke_role(
        self,
        user_id: str,
        role_id: str,
        workspace_id: str | None = None,
    ) -> bool:
        """Revoke a role from a user."""
        return await self._get_rbac_manager().revoke_role(user_id, role_id, workspace_id)

    async def check_permission(
        self,
        user_id: str,
        permission: Permission,
        workspace_id: str | None = None,
    ) -> bool:
        """Check if user has a permission."""
        return await self._get_rbac_manager().check_permission(user_id, permission, workspace_id)

    async def get_user_permissions(
        self,
        user_id: str,
        workspace_id: str | None = None,
    ) -> set[Permission]:
        """Get all permissions for a user."""
        return await self._get_rbac_manager().get_user_permissions(user_id, workspace_id)

    # Audit methods
    async def log_audit(
        self,
        action: AuditAction,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        workspace_id: str | None = None,
        details: dict[str, Any] | None = None,
        success: bool = True,
    ) -> AuditEntry:
        """Log an audit entry."""
        return await self._get_audit_trail().log(
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            details=details,
            success=success,
        )

    async def query_audit(
        self,
        actor_id: str | None = None,
        action: AuditAction | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries."""
        return await self._get_audit_trail().query(
            actor_id=actor_id,
            action=action,
            workspace_id=workspace_id,
            limit=limit,
        )

    async def get_user_activity(
        self,
        user_id: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get activity summary for a user."""
        return await self._get_audit_trail().get_user_activity(user_id, days)

    def get_governance_stats(self) -> dict[str, Any]:
        """Get governance statistics."""
        return {
            "audit": self._get_audit_trail().get_stats(),
        }


# Singleton instances
_rbac_manager: RBACManager | None = None
_audit_trail: AuditTrail | None = None


def get_rbac_manager() -> RBACManager:
    """Get the global RBAC manager instance."""
    global _rbac_manager
    if _rbac_manager is None:
        _rbac_manager = RBACManager()
    return _rbac_manager


def get_audit_trail() -> AuditTrail:
    """Get the global audit trail instance."""
    global _audit_trail
    if _audit_trail is None:
        _audit_trail = AuditTrail()
    return _audit_trail
