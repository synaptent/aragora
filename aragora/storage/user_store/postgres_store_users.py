"""
PostgresUserStore - User CRUD operations mixin.

Extracted from postgres_store.py for modularity.
Provides user creation, retrieval, update, deletion, preferences, and token management.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.billing.models import User
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


class UserOperationsMixin:
    """Mixin providing user CRUD operations for PostgresUserStore."""

    if TYPE_CHECKING:
        _pool: Any

    # =========================================================================
    # User Operations
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
        """Create a new user (sync wrapper)."""
        return run_async(
            self.create_user_async(email, password_hash, password_salt, name, org_id, role)
        )

    async def create_user_async(
        self,
        email: str,
        password_hash: str,
        password_salt: str,
        name: str = "",
        org_id: str | None = None,
        role: str = "member",
    ) -> User:
        """Create a new user asynchronously."""
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users
                   (id, email, password_hash, password_salt, name, org_id, role,
                    is_active, email_verified, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, FALSE, $8, $8)""",
                user_id,
                email,
                password_hash,
                password_salt,
                name,
                org_id,
                role,
                now,
            )

        return User(
            id=user_id,
            email=email,
            password_hash=password_hash,
            password_salt=password_salt,
            name=name,
            org_id=org_id,
            role=role,
            is_active=True,
            email_verified=False,
            created_at=now,
            updated_at=now,
        )

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID (sync wrapper)."""
        return run_async(self.get_user_by_id_async(user_id))

    async def get_user_by_id_async(self, user_id: str) -> User | None:
        """Get user by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, email, password_hash, password_salt, name, org_id, role,
                          is_active, email_verified, api_key, api_key_hash, api_key_prefix,
                          api_key_created_at, api_key_expires_at, created_at, updated_at,
                          last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes,
                          token_version, failed_login_attempts, lockout_until,
                          last_failed_login_at, preferences
                   FROM users WHERE id = $1""",
                user_id,
            )
            if row:
                return self._row_to_user(row)
            return None

    def get_users_batch(self, user_ids: list[str]) -> dict[str, User]:
        """Fetch multiple users in a single query (sync wrapper)."""
        return run_async(self.get_users_batch_async(user_ids))

    async def get_users_batch_async(self, user_ids: list[str]) -> dict[str, User]:
        """Fetch multiple users asynchronously."""
        if not user_ids:
            return {}

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, email, password_hash, password_salt, name, org_id, role,
                          is_active, email_verified, api_key, api_key_hash, api_key_prefix,
                          api_key_created_at, api_key_expires_at, created_at, updated_at,
                          last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes,
                          token_version, failed_login_attempts, lockout_until,
                          last_failed_login_at, preferences
                   FROM users WHERE id = ANY($1)""",
                user_ids,
            )
            return {row["id"]: self._row_to_user(row) for row in rows}

    def get_user_by_email(self, email: str) -> User | None:
        """Get user by email (sync wrapper)."""
        return run_async(self.get_user_by_email_async(email))

    async def get_user_by_email_async(self, email: str) -> User | None:
        """Get user by email asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, email, password_hash, password_salt, name, org_id, role,
                          is_active, email_verified, api_key, api_key_hash, api_key_prefix,
                          api_key_created_at, api_key_expires_at, created_at, updated_at,
                          last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes,
                          token_version, failed_login_attempts, lockout_until,
                          last_failed_login_at, preferences
                   FROM users WHERE email = $1""",
                email,
            )
            if row:
                return self._row_to_user(row)
            return None

    def get_user_by_api_key(self, api_key: str) -> User | None:
        """Get user by API key (sync wrapper)."""
        return run_async(self.get_user_by_api_key_async(api_key))

    async def get_user_by_api_key_async(self, api_key: str) -> User | None:
        """Get user by API key asynchronously."""
        import hashlib

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, email, password_hash, password_salt, name, org_id, role,
                          is_active, email_verified, api_key, api_key_hash, api_key_prefix,
                          api_key_created_at, api_key_expires_at, created_at, updated_at,
                          last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes,
                          token_version, failed_login_attempts, lockout_until,
                          last_failed_login_at, preferences
                   FROM users WHERE api_key_hash = $1 OR api_key = $2""",
                key_hash,
                api_key,
            )
            if row:
                return self._row_to_user(row)
            return None

    def update_user(self, user_id: str, **fields: Any) -> bool:
        """Update user fields (sync wrapper)."""
        return run_async(self.update_user_async(user_id, **fields))

    async def update_user_async(self, user_id: str, **fields: Any) -> bool:
        """Update user fields asynchronously."""
        if not fields:
            return False

        updates: list[str] = []
        params: list[Any] = []
        param_idx = 1

        for key, value in fields.items():
            updates.append(f"{key} = ${param_idx}")
            params.append(value)
            param_idx += 1

        updates.append(f"updated_at = ${param_idx}")
        params.append(datetime.now(timezone.utc))
        param_idx += 1
        params.append(user_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                # dynamic clause from internal state
                f"UPDATE users SET {', '.join(updates)} WHERE id = ${param_idx}",
                *params,
            )
            return result != "UPDATE 0"

    def update_users_batch(self, updates: list[dict[str, Any]]) -> int:
        """Update multiple users in a single transaction (sync wrapper)."""
        return run_async(self.update_users_batch_async(updates))

    async def update_users_batch_async(self, updates: list[dict[str, Any]]) -> int:
        """Update multiple users asynchronously."""
        count = 0
        for update in updates:
            update_fields = dict(update)
            user_id = update_fields.pop("user_id", None) or update_fields.pop("id", None)
            if user_id and update_fields:
                if await self.update_user_async(user_id, **update_fields):
                    count += 1
        return count

    def delete_user(self, user_id: str) -> bool:
        """Delete a user (sync wrapper)."""
        return run_async(self.delete_user_async(user_id))

    async def delete_user_async(self, user_id: str) -> bool:
        """Delete a user asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            return result != "DELETE 0"

    def get_user_preferences(self, user_id: str) -> dict | None:
        """Get user preferences (sync wrapper)."""
        return run_async(self.get_user_preferences_async(user_id))

    async def get_user_preferences_async(self, user_id: str) -> dict | None:
        """Get user preferences asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT preferences FROM users WHERE id = $1", user_id)
            if row and row["preferences"]:
                prefs = row["preferences"]
                return json.loads(prefs) if isinstance(prefs, str) else prefs
            return None

    def set_user_preferences(self, user_id: str, preferences: dict) -> bool:
        """Set user preferences (sync wrapper)."""
        return run_async(self.set_user_preferences_async(user_id, preferences))

    async def set_user_preferences_async(self, user_id: str, preferences: dict) -> bool:
        """Set user preferences asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET preferences = $1, updated_at = $2 WHERE id = $3",
                json.dumps(preferences),
                datetime.now(timezone.utc),
                user_id,
            )
            return result != "UPDATE 0"

    def increment_token_version(self, user_id: str) -> int:
        """Increment token version (sync wrapper)."""
        return run_async(self.increment_token_version_async(user_id))

    async def increment_token_version_async(self, user_id: str) -> int:
        """Increment token version asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE users SET token_version = token_version + 1, updated_at = $1
                   WHERE id = $2 RETURNING token_version""",
                datetime.now(timezone.utc),
                user_id,
            )
            return row["token_version"] if row else 1

    def _row_to_user(self, row: Any) -> User:
        """Convert database row to User object."""
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
            api_key_hash=row["api_key_hash"],
            api_key_prefix=row["api_key_prefix"],
            api_key_created_at=row["api_key_created_at"],
            api_key_expires_at=row["api_key_expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
            mfa_secret=row["mfa_secret"],
            mfa_enabled=bool(row["mfa_enabled"]),
            mfa_backup_codes=row["mfa_backup_codes"],
            token_version=row["token_version"] or 1,
        )
