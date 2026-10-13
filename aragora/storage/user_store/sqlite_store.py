"""
UserStore - SQLite backend for user and organization persistence.

Provides CRUD operations for:
- Users (registration, authentication, API keys)
- Organizations (team management, billing)
- Usage tracking (debate counts, monthly resets)

This class serves as a facade over specialized repositories:
- UserRepository: User CRUD and authentication
- OrganizationRepository: Team management and billing
- OAuthRepository: Social login provider linking
- UsageRepository: Rate limiting and usage tracking
- AuditRepository: Audit logging for compliance
- InvitationRepository: Organization invitation workflow
- SecurityRepository: Account lockout and login security

The repositories are created internally and methods delegate to them,
maintaining backward compatibility while enabling modular testing.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, ClassVar
from collections.abc import Iterator

from aragora.config import resolve_db_path
from aragora.billing.models import Organization, OrganizationInvitation, SubscriptionTier, User
from aragora.storage.repositories import (
    AuditRepository,
    InvitationRepository,
    OAuthRepository,
    OrganizationRepository,
    SecurityRepository,
    UsageRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)


class UserStore:
    """
    SQLite-backed storage for users and organizations.

    Thread-safe with connection pooling via thread-local storage.
    Uses WAL mode for better read/write concurrency.
    """

    # Explicit columns for SELECT queries - prevents SELECT * data exposure
    # Note: api_key is included for legacy support (plaintext -> hash migration)
    _USER_COLUMNS: ClassVar[str] = (
        "id, email, password_hash, password_salt, name, org_id, role, "
        "is_active, email_verified, api_key, api_key_hash, api_key_prefix, "
        "api_key_created_at, api_key_expires_at, created_at, updated_at, "
        "last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes, token_version"
    )
    _ORG_COLUMNS: ClassVar[str] = (
        "id, name, slug, tier, owner_id, stripe_customer_id, "
        "stripe_subscription_id, debates_used_this_month, billing_cycle_start, "
        "settings, created_at, updated_at"
    )
    _INVITATION_COLUMNS: ClassVar[str] = (
        "id, org_id, email, role, token, invited_by, status, "
        "created_at, expires_at, accepted_by, accepted_at"
    )
    _AUDIT_LOG_COLUMNS: ClassVar[str] = (
        "id, timestamp, user_id, org_id, action, resource_type, "
        "resource_id, old_value, new_value, metadata, ip_address, user_agent"
    )

    # Class-level lock for schema migrations to prevent race conditions
    _schema_lock = threading.Lock()

    # Lockout policy constants (delegated from SecurityRepository for backward compatibility)
    LOCKOUT_THRESHOLD_1 = SecurityRepository.LOCKOUT_THRESHOLD_1
    LOCKOUT_THRESHOLD_2 = SecurityRepository.LOCKOUT_THRESHOLD_2
    LOCKOUT_THRESHOLD_3 = SecurityRepository.LOCKOUT_THRESHOLD_3
    LOCKOUT_DURATION_1 = SecurityRepository.LOCKOUT_DURATION_1
    LOCKOUT_DURATION_2 = SecurityRepository.LOCKOUT_DURATION_2
    LOCKOUT_DURATION_3 = SecurityRepository.LOCKOUT_DURATION_3

    def __init__(self, db_path: Path | str):
        """
        Initialize UserStore.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(resolve_db_path(db_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"userstore_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._init_schema()

        # Initialize specialized repositories
        self._user_repo = UserRepository(self._transaction, self._get_connection)
        self._org_repo = OrganizationRepository(self._transaction, self._row_to_user)
        self._oauth_repo = OAuthRepository(self._transaction)
        self._usage_repo = UsageRepository(self._transaction, self.get_organization_by_id)
        self._audit_repo = AuditRepository(self._transaction)
        self._invitation_repo = InvitationRepository(self._transaction)
        self._security_repo = SecurityRepository(self._transaction)

    def _get_connection(self) -> sqlite3.Connection:
        """Get per-context database connection (async-safe)."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database transactions."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except (sqlite3.Error, OSError, ValueError) as e:
            conn.rollback()
            logger.debug("Transaction rolled back due to: %s", e)
            raise

    def _init_schema(self) -> None:
        """Initialize database schema with migration support."""
        with self._schema_lock, self._transaction() as cursor:
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    org_id TEXT,
                    role TEXT DEFAULT 'member',
                    is_active INTEGER DEFAULT 1,
                    email_verified INTEGER DEFAULT 0,
                    api_key TEXT UNIQUE,
                    api_key_hash TEXT UNIQUE,
                    api_key_prefix TEXT,
                    api_key_created_at TEXT,
                    api_key_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    FOREIGN KEY (org_id) REFERENCES organizations(id)
                )
            """)

            self._migrate_api_key_columns(cursor)

            # Organizations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS organizations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'free',
                    owner_id TEXT,
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    debates_used_this_month INTEGER DEFAULT 0,
                    billing_cycle_start TEXT NOT NULL,
                    settings TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (owner_id) REFERENCES users(id)
                )
            """)

            # Usage events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (org_id) REFERENCES organizations(id)
                )
            """)

            # OAuth providers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS oauth_providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_user_id TEXT NOT NULL,
                    email TEXT,
                    linked_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(provider, provider_user_id)
                )
            """)

            # Audit log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id TEXT,
                    org_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    metadata TEXT DEFAULT '{}',
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (org_id) REFERENCES organizations(id)
                )
            """)

            # Organization invitations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS org_invitations (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    token TEXT UNIQUE NOT NULL,
                    invited_by TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    accepted_at TEXT,
                    FOREIGN KEY (org_id) REFERENCES organizations(id),
                    FOREIGN KEY (invited_by) REFERENCES users(id)
                )
            """)

            # Create indexes
            self._create_indexes(cursor)

        logger.info("UserStore initialized: %s", self.db_path)

    def _create_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Create database indexes."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_key_hash ON users(api_key_hash)",
            "CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug)",
            "CREATE INDEX IF NOT EXISTS idx_orgs_stripe ON organizations(stripe_customer_id)",
            "CREATE INDEX IF NOT EXISTS idx_usage_org ON usage_events(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_user ON oauth_providers(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_provider ON oauth_providers(provider, provider_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_log(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)",
            "CREATE INDEX IF NOT EXISTS idx_invitations_org ON org_invitations(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_invitations_email ON org_invitations(email)",
            "CREATE INDEX IF NOT EXISTS idx_invitations_token ON org_invitations(token)",
            "CREATE INDEX IF NOT EXISTS idx_invitations_status ON org_invitations(status)",
            # Composite indexes for common query patterns
            "CREATE INDEX IF NOT EXISTS idx_users_org_role ON users(org_id, role)",
            "CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_usage_org_type ON usage_events(org_id, event_type)",
        ]
        for idx in indexes:
            cursor.execute(idx)

    def _migrate_api_key_columns(self, cursor: sqlite3.Cursor) -> None:
        """Migrate schema to add new columns if they don't exist."""
        cursor.execute("PRAGMA table_info(users)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        migrations = [
            ("api_key_hash", "ALTER TABLE users ADD COLUMN api_key_hash TEXT"),
            ("api_key_prefix", "ALTER TABLE users ADD COLUMN api_key_prefix TEXT"),
            ("api_key_expires_at", "ALTER TABLE users ADD COLUMN api_key_expires_at TEXT"),
            ("mfa_secret", "ALTER TABLE users ADD COLUMN mfa_secret TEXT"),
            ("mfa_enabled", "ALTER TABLE users ADD COLUMN mfa_enabled INTEGER DEFAULT 0"),
            ("mfa_backup_codes", "ALTER TABLE users ADD COLUMN mfa_backup_codes TEXT"),
            ("token_version", "ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 1"),
            (
                "failed_login_attempts",
                "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0",
            ),
            ("lockout_until", "ALTER TABLE users ADD COLUMN lockout_until TEXT"),
            ("last_failed_login_at", "ALTER TABLE users ADD COLUMN last_failed_login_at TEXT"),
            ("preferences", "ALTER TABLE users ADD COLUMN preferences TEXT DEFAULT '{}'"),
        ]

        for col_name, sql in migrations:
            if col_name not in existing_columns:
                cursor.execute(sql)
                logger.info("Migration: Added %s column", col_name)

    def migrate_plaintext_api_keys(self) -> int:
        """Migrate existing plaintext API keys to hashed storage."""
        migrated = 0
        with self._transaction() as cursor:
            cursor.execute("""
                SELECT id, api_key, api_key_created_at
                FROM users
                WHERE api_key IS NOT NULL AND api_key_hash IS NULL
            """)

            for row in cursor.fetchall():
                user_id, api_key, _ = row[0], row[1], row[2]
                key_hash = hashlib.sha256(api_key.encode()).hexdigest()
                prefix = api_key[:12]
                expires_at = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

                cursor.execute(
                    """
                    UPDATE users
                    SET api_key_hash = ?, api_key_prefix = ?, api_key_expires_at = ?, updated_at = ?
                    WHERE id = ?
                """,
                    (key_hash, prefix, expires_at, datetime.now(timezone.utc).isoformat(), user_id),
                )
                migrated += 1
                logger.info("Migrated API key for user %s", user_id)

        logger.info("API key migration complete: %s keys migrated", migrated)
        return migrated

    # =========================================================================
    # User Operations (delegated to UserRepository)
    # =========================================================================

    def create_user(
        self,
        email: str,
        password_hash: str,
        password_salt: str,
        name: str = "",
        org_id: str | None = None,
        role: str = "member",
    ) -> User:
        """Create a new user."""
        return self._user_repo.create(email, password_hash, password_salt, name, org_id, role)

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        return self._user_repo.get_by_id(user_id)

    def get_users_batch(self, user_ids: list[str]) -> dict[str, User]:
        """Fetch multiple users in a single query."""
        return self._user_repo.get_batch(user_ids)

    def get_user_by_email(self, email: str) -> User | None:
        """Get user by email."""
        return self._user_repo.get_by_email(email)

    def get_user_by_api_key(self, api_key: str) -> User | None:
        """Get user by API key.

        Returns None if the API key is expired.
        """
        user = self._user_repo.get_by_api_key(api_key)
        if user and hasattr(user, "api_key_expires_at") and user.api_key_expires_at:
            if isinstance(user.api_key_expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(
                        user.api_key_expires_at.replace("Z", "+00:00")
                    )
                    if expires_at < datetime.now(timezone.utc):
                        logger.warning("Attempted use of expired API key for user %s", user.id)
                        return None
                except (ValueError, AttributeError):
                    pass  # If we can't parse the date, allow the key
            elif isinstance(user.api_key_expires_at, datetime):
                if user.api_key_expires_at < datetime.now(timezone.utc):
                    logger.warning("Attempted use of expired API key for user %s", user.id)
                    return None
        return user

    def update_user(self, user_id: str, **fields) -> bool:
        """Update user fields."""
        return self._user_repo.update(user_id, **fields)

    def update_users_batch(self, updates: list[dict[str, Any]]) -> int:
        """Update multiple users in a single transaction."""
        return self._user_repo.update_batch(updates)

    def delete_user(self, user_id: str) -> bool:
        """Delete a user."""
        return self._user_repo.delete(user_id)

    def get_user_preferences(self, user_id: str) -> dict | None:
        """Get user preferences."""
        return self._user_repo.get_preferences(user_id)

    def set_user_preferences(self, user_id: str, preferences: dict) -> bool:
        """Set user preferences."""
        return self._user_repo.set_preferences(user_id, preferences)

    def increment_token_version(self, user_id: str) -> int:
        """Increment token version, invalidating all existing tokens."""
        return self._user_repo.increment_token_version(user_id)

    def _row_to_user(self, row: sqlite3.Row) -> User:
        """Convert database row to User object."""
        return UserRepository._row_to_user(row)

    # =========================================================================
    # Organization Operations (delegated to OrganizationRepository)
    # =========================================================================

    def create_organization(
        self,
        name: str,
        owner_id: str,
        slug: str | None = None,
        tier: SubscriptionTier = SubscriptionTier.FREE,
    ) -> Organization:
        """Create a new organization."""
        return self._org_repo.create(name, owner_id, slug, tier)

    def get_organization_by_id(self, org_id: str) -> Organization | None:
        """Get organization by ID."""
        return self._org_repo.get_by_id(org_id)

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        """Get organization by slug."""
        return self._org_repo.get_by_slug(slug)

    def get_organization_by_stripe_customer(self, stripe_customer_id: str) -> Organization | None:
        """Get organization by Stripe customer ID."""
        return self._org_repo.get_by_stripe_customer(stripe_customer_id)

    def get_organization_by_subscription(self, subscription_id: str) -> Organization | None:
        """Get organization by Stripe subscription ID."""
        return self._org_repo.get_by_subscription(subscription_id)

    def reset_org_usage(self, org_id: str) -> bool:
        """Reset monthly usage for a single organization."""
        return self._org_repo.reset_usage(org_id)

    def update_organization(self, org_id: str, **fields) -> bool:
        """Update organization fields."""
        return self._org_repo.update(org_id, **fields)

    def add_user_to_org(self, user_id: str, org_id: str, role: str = "member") -> bool:
        """Add user to organization."""
        return self._org_repo.add_member(user_id, org_id, role)

    def remove_user_from_org(self, user_id: str) -> bool:
        """Remove user from organization."""
        return self._org_repo.remove_member(user_id)

    def get_org_members(self, org_id: str) -> list[User]:
        """Get all members of an organization."""
        return self._org_repo.get_members(org_id)

    def get_org_members_eager(self, org_id: str) -> tuple[Organization | None, list[User]]:
        """Get organization and all its members in a single query operation."""
        return self._org_repo.get_with_members(org_id)

    def get_orgs_with_members_batch(
        self, org_ids: list[str]
    ) -> dict[str, tuple[Organization, list[User]]]:
        """Get multiple organizations with their members in optimized queries."""
        return self._org_repo.get_batch_with_members(org_ids)

    def _row_to_org(self, row: sqlite3.Row) -> Organization:
        """Convert database row to Organization object."""
        return OrganizationRepository._row_to_org(row)

    # =========================================================================
    # Organization Invitations (delegated to InvitationRepository)
    # =========================================================================

    def create_invitation(self, invitation: OrganizationInvitation) -> bool:
        """Create a new organization invitation."""
        return self._invitation_repo.create_invitation(invitation)

    def get_invitation_by_id(self, invitation_id: str) -> OrganizationInvitation | None:
        """Get invitation by ID."""
        return self._invitation_repo.get_by_id(invitation_id)

    def get_invitation_by_token(self, token: str) -> OrganizationInvitation | None:
        """Get invitation by token."""
        return self._invitation_repo.get_by_token(token)

    def get_invitation_by_email(self, org_id: str, email: str) -> OrganizationInvitation | None:
        """Get pending invitation by org and email."""
        return self._invitation_repo.get_by_email(org_id, email)

    def get_invitations_for_org(self, org_id: str) -> list[OrganizationInvitation]:
        """Get all invitations for an organization."""
        return self._invitation_repo.get_for_org(org_id)

    def get_pending_invitations_by_email(self, email: str) -> list[OrganizationInvitation]:
        """Get all pending invitations for an email address."""
        return self._invitation_repo.get_pending_by_email(email)

    def update_invitation_status(
        self,
        invitation_id: str,
        status: str,
        accepted_at: datetime | None = None,
    ) -> bool:
        """Update invitation status."""
        return self._invitation_repo.update_status(invitation_id, status, accepted_at)

    def delete_invitation(self, invitation_id: str) -> bool:
        """Delete an invitation."""
        return self._invitation_repo.delete(invitation_id)

    def cleanup_expired_invitations(self) -> int:
        """Mark expired invitations as expired."""
        return self._invitation_repo.cleanup_expired()

    # =========================================================================
    # Usage Tracking (delegated to UsageRepository)
    # =========================================================================

    def increment_usage(self, org_id: str, count: int = 1) -> int:
        """Increment debate usage for an organization."""
        return self._usage_repo.increment(org_id, count)

    def record_usage_event(
        self,
        org_id: str,
        event_type: str,
        count: int = 1,
        metadata: dict | None = None,
    ) -> None:
        """Record a usage event for analytics."""
        self._usage_repo.record_event(org_id, event_type, count, metadata)

    def reset_monthly_usage(self) -> int:
        """Reset monthly usage for all organizations."""
        return self._usage_repo.reset_all_monthly()

    def get_usage_summary(self, org_id: str) -> dict:
        """Get usage summary for an organization."""
        return self._usage_repo.get_summary(org_id)

    # =========================================================================
    # OAuth Provider Operations (delegated to OAuthRepository)
    # =========================================================================

    def link_oauth_provider(
        self,
        user_id: str,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
    ) -> bool:
        """Link an OAuth provider to a user account."""
        return self._oauth_repo.link_provider(user_id, provider, provider_user_id, email)

    def unlink_oauth_provider(self, user_id: str, provider: str) -> bool:
        """Unlink an OAuth provider from a user account."""
        return self._oauth_repo.unlink_provider(user_id, provider)

    def get_user_by_oauth(self, provider: str, provider_user_id: str) -> User | None:
        """Get user by OAuth provider ID."""
        user_id = self._oauth_repo.get_user_id_by_provider(provider, provider_user_id)
        return self.get_user_by_id(user_id) if user_id else None

    def get_user_oauth_providers(self, user_id: str) -> list[dict]:
        """Get all OAuth providers linked to a user."""
        return self._oauth_repo.get_providers_for_user(user_id)

    # =========================================================================
    # Audit Logging Operations (delegated to AuditRepository)
    # =========================================================================

    def log_audit_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """Log an audit event."""
        return self._audit_repo.log_event(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            org_id=org_id,
            old_value=old_value,
            new_value=new_value,
            metadata=metadata,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def get_audit_log(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query audit log entries."""
        return self._audit_repo.get_log(
            org_id=org_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    def get_audit_log_count(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> int:
        """Get count of audit log entries matching filters."""
        return self._audit_repo.get_log_count(
            org_id=org_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
        )

    # =========================================================================
    # Account Lockout Methods (delegated to SecurityRepository)
    # =========================================================================

    def is_account_locked(self, email: str) -> tuple[bool, datetime | None, int]:
        """Check if an account is currently locked."""
        return self._security_repo.is_account_locked(email)

    def record_failed_login(self, email: str) -> tuple[int, datetime | None]:
        """Record a failed login attempt and potentially lock the account."""
        return self._security_repo.record_failed_login(email)

    def reset_failed_login_attempts(self, email: str) -> bool:
        """Reset failed login attempts after successful login."""
        return self._security_repo.reset_failed_login_attempts(email)

    def get_lockout_info(self, email: str) -> dict:
        """Get detailed lockout information for an account."""
        return self._security_repo.get_lockout_info(email)

    # =========================================================================
    # Admin Methods (for admin panel)
    # =========================================================================

    def list_all_organizations(
        self,
        limit: int = 50,
        offset: int = 0,
        tier_filter: str | None = None,
    ) -> tuple[list[Organization], int]:
        """List all organizations with pagination."""
        conn = self._get_connection()
        cursor = conn.cursor()

        where_clause = ""
        params: list[Any] = []
        if tier_filter:
            where_clause = "WHERE tier = ?"
            params.append(tier_filter)

        # nosec B608: where_clause is built from constants, tier_filter is parameterized
        cursor.execute(f"SELECT COUNT(*) FROM organizations {where_clause}", params)  # nosec B608
        total = cursor.fetchone()[0]

        # nosec B608: where_clause is built from constants, all values are parameterized
        query = f"""
            SELECT {self._ORG_COLUMNS} FROM organizations
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """  # nosec B608
        params.extend([limit, offset])
        cursor.execute(query, params)

        return [self._row_to_org(row) for row in cursor.fetchall()], total

    def list_all_users(
        self,
        limit: int = 50,
        offset: int = 0,
        org_id_filter: str | None = None,
        role_filter: str | None = None,
        active_only: bool = False,
    ) -> tuple[list[User], int]:
        """List all users with pagination and filtering."""
        conn = self._get_connection()
        cursor = conn.cursor()

        conditions = []
        params: list[Any] = []

        if org_id_filter:
            conditions.append("org_id = ?")
            params.append(org_id_filter)
        if role_filter:
            conditions.append("role = ?")
            params.append(role_filter)
        if active_only:
            conditions.append("is_active = 1")

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # nosec B608: where_clause is built from constants, all filter values are parameterized
        cursor.execute(f"SELECT COUNT(*) FROM users {where_clause}", params.copy())  # nosec B608
        total = cursor.fetchone()[0]

        # nosec B608: where_clause is built from constants, all values are parameterized
        query = f"""
            SELECT {self._USER_COLUMNS} FROM users
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """  # nosec B608
        params.extend([limit, offset])
        cursor.execute(query, params)

        return [self._row_to_user(row) for row in cursor.fetchall()], total

    def get_admin_stats(self) -> dict:
        """Get system-wide statistics for admin dashboard."""
        conn = self._get_connection()
        cursor = conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) FROM users")
        stats["total_users"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        stats["active_users"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM organizations")
        stats["total_organizations"] = cursor.fetchone()[0]

        cursor.execute("SELECT tier, COUNT(*) as count FROM organizations GROUP BY tier")
        stats["tier_distribution"] = {row["tier"]: row["count"] for row in cursor.fetchall()}

        cursor.execute("SELECT SUM(debates_used_this_month) as total FROM organizations")
        result = cursor.fetchone()
        stats["total_debates_this_month"] = result["total"] or 0

        cursor.execute("SELECT COUNT(*) FROM users WHERE last_login_at > datetime('now', '-1 day')")
        stats["users_active_24h"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-7 days')")
        stats["new_users_7d"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM organizations WHERE created_at > datetime('now', '-7 days')"
        )
        stats["new_orgs_7d"] = cursor.fetchone()[0]

        return stats

    def close(self) -> None:
        """Close all database connections."""
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except (sqlite3.Error, OSError) as e:
                    logger.debug("Error closing connection: %s", e)
            self._connections.clear()
