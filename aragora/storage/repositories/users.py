"""
UserRepository - User identity and authentication operations.

Extracted from UserStore for better modularity. Manages user CRUD operations,
authentication lookups, preferences, and token versioning.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from contextlib import AbstractContextManager
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.billing.models import User
    from aragora.storage.user_store import PostgresUserStore, UserStore

logger = logging.getLogger(__name__)

# MFA fields that require encryption
_MFA_SENSITIVE_FIELDS = {"mfa_secret", "mfa_backup_codes"}


def _encrypt_mfa_field(value: str, user_id: str) -> str:
    """Encrypt MFA-related field for storage."""
    if not value:
        return value
    try:
        from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

        if not CRYPTO_AVAILABLE:
            return value
        service = get_encryption_service()
        encrypted = service.encrypt(value, associated_data=user_id)
        return encrypted.to_base64()
    except (ValueError, RuntimeError, OSError, ImportError) as e:
        logger.warning("MFA field encryption failed: %s", e)
        return value


def _decrypt_mfa_field(value: str, user_id: str) -> str:
    """Decrypt MFA-related field, handling legacy unencrypted values."""
    if not value:
        return value
    try:
        from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

        if not CRYPTO_AVAILABLE:
            return value
        # Check if it looks encrypted (base64-encoded EncryptedData starts with version byte)
        if not value.startswith("A"):
            return value  # Legacy unencrypted
        service = get_encryption_service()
        return service.decrypt_string(value, associated_data=user_id)
    except (ValueError, RuntimeError, OSError, ImportError) as e:
        logger.debug("MFA field decryption failed (may be legacy): %s", e)
        return value


class UserRepository:
    """
    Repository for user identity and authentication operations.

    This class manages:
    - User CRUD operations (create, read, update, delete)
    - Authentication lookups (by email, API key)
    - User preferences storage
    - Token version management for session invalidation
    """

    # Explicit columns for SELECT queries - prevents SELECT * data exposure
    # Note: api_key is included for legacy support (plaintext -> hash migration)
    _USER_COLUMNS = (
        "id, email, password_hash, password_salt, name, org_id, role, "
        "is_active, email_verified, api_key, api_key_hash, api_key_prefix, "
        "api_key_created_at, api_key_expires_at, created_at, updated_at, "
        "last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes, token_version"
    )

    # Column mapping for update operations
    _COLUMN_MAP = {
        "email": "email",
        "password_hash": "password_hash",
        "password_salt": "password_salt",
        "name": "name",
        "org_id": "org_id",
        "role": "role",
        "is_active": "is_active",
        "email_verified": "email_verified",
        "api_key_hash": "api_key_hash",
        "api_key_prefix": "api_key_prefix",
        "api_key_created_at": "api_key_created_at",
        "api_key_expires_at": "api_key_expires_at",
        "last_login_at": "last_login_at",
        "mfa_secret": "mfa_secret",
        "mfa_enabled": "mfa_enabled",
        "mfa_backup_codes": "mfa_backup_codes",
    }

    def __init__(
        self,
        transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]],
        get_connection_fn: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        """
        Initialize the user repository.

        Args:
            transaction_fn: Function that returns a transaction context manager
                           with a cursor.
            get_connection_fn: Optional function to get raw connection for
                              non-transactional reads.
        """
        self._transaction = transaction_fn
        self._get_connection = get_connection_fn

    def create(
        self,
        email: str,
        password_hash: str,
        password_salt: str,
        name: str = "",
        org_id: str | None = None,
        role: str = "member",
    ) -> User:
        """
        Create a new user.

        Args:
            email: User email (must be unique)
            password_hash: Hashed password
            password_salt: Password salt
            name: Display name
            org_id: Organization ID
            role: Role in organization

        Returns:
            Created User object

        Raises:
            ValueError: If email already exists
        """
        from aragora.billing.models import User

        user = User(
            email=email,
            password_hash=password_hash,
            password_salt=password_salt,
            name=name,
            org_id=org_id,
            role=role,
        )

        try:
            with self._transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        id, email, password_hash, password_salt, name, org_id, role,
                        is_active, email_verified, api_key_created_at,
                        created_at, updated_at, last_login_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.id,
                        user.email,
                        user.password_hash,
                        user.password_salt,
                        user.name,
                        user.org_id,
                        user.role,
                        1 if user.is_active else 0,
                        1 if user.email_verified else 0,
                        user.api_key_created_at.isoformat() if user.api_key_created_at else None,
                        user.created_at.isoformat(),
                        user.updated_at.isoformat(),
                        user.last_login_at.isoformat() if user.last_login_at else None,
                    ),
                )
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: users.email" in str(e):
                raise ValueError(f"Email already exists: {email}")
            raise

        logger.info("user_created id=%s email=%s", user.id, email)
        return user

    def get_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        with self._transaction() as cursor:
            # column name interpolation, parameterized
            cursor.execute(f"SELECT {self._USER_COLUMNS} FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return self._row_to_user(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        """Get user by email."""
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._USER_COLUMNS} FROM users WHERE email = ?",  # column constant
                (email.lower(),),
            )
            row = cursor.fetchone()
            return self._row_to_user(row) if row else None

    def get_by_api_key(self, api_key: str) -> User | None:
        """
        Get user by API key using hash-based lookup.

        Args:
            api_key: The plaintext API key to verify

        Returns:
            User if found and key is valid/not expired, None otherwise
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._USER_COLUMNS} FROM users WHERE api_key_hash = ?",  # column constant
                (key_hash,),
            )
            row = cursor.fetchone()

            if row:
                user = self._row_to_user(row)
                # Check expiration
                if user.api_key_expires_at and datetime.now(timezone.utc) > user.api_key_expires_at:
                    logger.debug("API key expired for user %s", user.id)
                    return None
                return user

        return None

    def get_batch(self, user_ids: list[str]) -> dict[str, User]:
        """
        Fetch multiple users in a single query.

        More efficient than calling get_by_id in a loop (N+1 pattern).

        Args:
            user_ids: List of user IDs to fetch

        Returns:
            Dict mapping user_id to User object for found users
        """
        if not user_ids:
            return {}

        unique_ids = list(dict.fromkeys(user_ids))

        with self._transaction() as cursor:
            placeholders = ",".join("?" * len(unique_ids))
            query = f"SELECT {self._USER_COLUMNS} FROM users WHERE id IN ({placeholders})"  # nosec B608
            cursor.execute(query, unique_ids)
            return {row["id"]: self._row_to_user(row) for row in cursor.fetchall()}

    def update(self, user_id: str, **fields: Any) -> bool:
        """
        Update user fields.

        Args:
            user_id: User ID
            **fields: Fields to update

        Returns:
            True if user was updated
        """
        if not fields:
            return False

        updates: list[str] = []
        values: list[Any] = []

        for field, value in fields.items():
            if field in self._COLUMN_MAP:
                updates.append(f"{self._COLUMN_MAP[field]} = ?")
                if isinstance(value, bool):
                    values.append(1 if value else 0)
                elif isinstance(value, datetime):
                    values.append(value.isoformat())
                elif field in _MFA_SENSITIVE_FIELDS and value:
                    # Encrypt MFA-related sensitive fields
                    values.append(_encrypt_mfa_field(str(value), user_id))
                else:
                    values.append(value)

        if not updates:
            return False

        updates.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(user_id)

        with self._transaction() as cursor:
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"  # nosec B608
            cursor.execute(query, values)
            return cursor.rowcount > 0

    def update_batch(self, updates: list[dict[str, Any]]) -> int:
        """
        Update multiple users in a single transaction.

        More efficient than calling update in a loop.

        Args:
            updates: List of dicts, each containing 'user_id' and fields to update.

        Returns:
            Number of users successfully updated
        """
        if not updates:
            return 0

        updated_count = 0
        now = datetime.now(timezone.utc).isoformat()

        # Group updates by the set of fields being updated
        field_groups: dict[tuple[str, ...], list[dict]] = {}
        for update in updates:
            if "user_id" not in update:
                continue
            fields = tuple(sorted(k for k in update.keys() if k != "user_id"))
            if fields not in field_groups:
                field_groups[fields] = []
            field_groups[fields].append(update)

        with self._transaction() as cursor:
            for fields, group in field_groups.items():
                valid_fields = [f for f in fields if f in self._COLUMN_MAP]
                if not valid_fields:
                    continue

                set_clauses = [f"{self._COLUMN_MAP[f]} = ?" for f in valid_fields]
                set_clauses.append("updated_at = ?")
                sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?"  # nosec B608

                params_list = []
                for update in group:
                    values: list[Any] = []
                    for field in valid_fields:
                        value = update[field]
                        if isinstance(value, bool):
                            values.append(1 if value else 0)
                        elif isinstance(value, datetime):
                            values.append(value.isoformat())
                        else:
                            values.append(value)
                    values.append(now)
                    values.append(update["user_id"])
                    params_list.append(tuple(values))

                cursor.executemany(sql, params_list)
                updated_count += cursor.rowcount

        return updated_count

    def delete(self, user_id: str) -> bool:
        """Delete a user."""
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return cursor.rowcount > 0

    def get_preferences(self, user_id: str) -> dict | None:
        """
        Get user preferences (feature toggles, settings).

        Args:
            user_id: User ID

        Returns:
            Dict of preferences, or None if user not found
        """
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT preferences FROM users WHERE id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    logger.warning("Invalid preferences JSON for user %s", user_id)
                    return {}
            return {} if row else None

    def set_preferences(self, user_id: str, preferences: dict) -> bool:
        """
        Set user preferences (feature toggles, settings).

        Args:
            user_id: User ID
            preferences: Dict of preferences to store

        Returns:
            True if preferences were saved
        """
        prefs_json = json.dumps(preferences)
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE users SET preferences = ?, updated_at = ? WHERE id = ?",
                (prefs_json, datetime.now(timezone.utc).isoformat(), user_id),
            )
            return cursor.rowcount > 0

    def increment_token_version(self, user_id: str) -> int:
        """
        Increment a user's token version, invalidating all existing tokens.

        Used for "logout all devices" functionality.

        Args:
            user_id: User ID to increment token version for

        Returns:
            The new token version, or 0 if user not found
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET token_version = COALESCE(token_version, 1) + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), user_id),
            )

            if cursor.rowcount == 0:
                logger.warning("increment_token_version: user %s not found", user_id)
                return 0

            cursor.execute(
                "SELECT token_version FROM users WHERE id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            new_version = row[0] if row else 1

            logger.info("token_version_incremented user_id=%s new_version=%s", user_id, new_version)
            return new_version

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        """Convert database row to User object."""
        from aragora.billing.models import User

        def safe_get(name: str, default=None):
            try:
                return row[name]
            except (IndexError, KeyError):
                return default

        def parse_datetime(value) -> datetime | None:
            """Parse datetime from ISO string or Unix timestamp."""
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value, tz=timezone.utc)
            try:
                # Try ISO format first
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                # Try parsing as float (Unix timestamp stored as string)
                try:
                    return datetime.fromtimestamp(float(value), tz=timezone.utc)
                except (ValueError, OSError):
                    logger.warning("Could not parse datetime: %s", value)
                    return datetime.now(timezone.utc)

        return User(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            password_salt=row["password_salt"],
            name=row["name"] or "",
            org_id=row["org_id"],
            role=row["role"] or "member",
            is_active=bool(row["is_active"]),
            email_verified=bool(row["email_verified"]),
            api_key_hash=safe_get("api_key_hash"),
            api_key_prefix=safe_get("api_key_prefix"),
            api_key_created_at=(
                parse_datetime(row["api_key_created_at"]) if row["api_key_created_at"] else None
            ),
            api_key_expires_at=parse_datetime(safe_get("api_key_expires_at")),
            created_at=parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=parse_datetime(row["updated_at"]) or datetime.now(timezone.utc),
            last_login_at=parse_datetime(row["last_login_at"]),
            mfa_secret=_decrypt_mfa_field(safe_get("mfa_secret") or "", row["id"]),
            mfa_enabled=bool(safe_get("mfa_enabled", 0)),
            mfa_backup_codes=_decrypt_mfa_field(safe_get("mfa_backup_codes") or "", row["id"]),
            token_version=safe_get("token_version", 1) or 1,
        )


_user_repository: UserRepository | None = None


def get_user_repository(
    store: UserStore | PostgresUserStore | None = None,
) -> UserRepository | None:
    """Get or create the user repository from the configured user store."""
    global _user_repository
    if _user_repository is not None:
        return _user_repository

    if store is None:
        try:
            from aragora.storage.user_store import get_user_store
        except ImportError:
            return None
        store = get_user_store()
    if store is None:
        return None

    repo = getattr(store, "_user_repo", None)
    if repo is None:
        # UserRepository requires a SQLite-style _transaction method
        # PostgresUserStore uses async operations and doesn't have this method
        transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]] | None = getattr(
            store, "_transaction", None
        )
        if transaction_fn is None:
            return None
        repo = UserRepository(
            transaction_fn,
            getattr(store, "_get_connection", None),
        )
    _user_repository = repo
    return _user_repository


def reset_user_repository() -> None:
    """Reset the cached user repository (useful for tests)."""
    global _user_repository
    _user_repository = None
