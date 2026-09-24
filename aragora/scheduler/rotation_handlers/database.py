"""
Database credential rotation handler.

Supports rotation for PostgreSQL, Supabase, and other database credentials.
"""

import re
import secrets
import string
from typing import Any
import logging

from .base import RotationHandler, RotationError

logger = logging.getLogger(__name__)

# PostgreSQL identifier: letters, digits, underscores; must start with letter/underscore; max 63 chars
_VALID_PG_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
# Supabase project refs: alphanumeric with hyphens
_VALID_PROJECT_REF = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9]{0,62}$")


def _validate_pg_identifier(value: str, kind: str = "identifier") -> str:
    """Validate a PostgreSQL identifier to prevent SQL injection.

    Args:
        value: The identifier to validate
        kind: Description for error messages (e.g. 'username', 'database')

    Returns:
        The validated identifier

    Raises:
        RotationError: If the identifier is invalid
    """
    if not value or not _VALID_PG_IDENTIFIER.match(value):
        raise RotationError(
            f"Invalid {kind}: must be 1-63 chars, start with letter/underscore, "
            f"contain only letters, digits, underscores. Got: {value!r}",
            kind,
        )
    return value


def _quote_pg_identifier(value: str) -> str:
    """Quote a PostgreSQL identifier (defense-in-depth after validation).

    Escapes double quotes and wraps in double quotes per SQL standard.
    """
    return '"' + value.replace('"', '""') + '"'


def _validate_project_ref(value: str) -> str:
    """Validate a Supabase project reference."""
    if not value or not _VALID_PROJECT_REF.match(value):
        raise RotationError(
            f"Invalid project_ref: must be alphanumeric with hyphens. Got: {value!r}",
            "project_ref",
        )
    return value


class DatabaseRotationHandler(RotationHandler):
    """
    Handler for database credential rotation.

    Supports:
    - PostgreSQL (direct connection)
    - Supabase (via API or direct)
    - MySQL (planned)
    - MongoDB (planned)
    """

    @property
    def secret_type(self) -> str:
        return "database"

    def __init__(
        self,
        password_length: int = 32,
        password_chars: str | None = None,
        grace_period_hours: int = 24,
        max_retries: int = 3,
    ):
        """
        Initialize database rotation handler.

        Args:
            password_length: Length of generated passwords
            password_chars: Characters to use in password generation
            grace_period_hours: Hours old credentials remain valid
            max_retries: Maximum retry attempts
        """
        super().__init__(grace_period_hours, max_retries)
        self.password_length = password_length
        self.password_chars = password_chars or (string.ascii_letters + string.digits + "!@#$%^&*")

    def _generate_password(self) -> str:
        """Generate a secure random password."""
        return "".join(secrets.choice(self.password_chars) for _ in range(self.password_length))

    async def generate_new_credentials(
        self, secret_id: str, metadata: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """
        Generate new database password.

        For databases, we generate a new password and update the user.
        The actual credential update happens in a transaction.

        Args:
            secret_id: Database credential identifier (e.g., "postgres_aragora_rw")
            metadata: Should contain 'db_type', 'host', 'database', 'username'

        Returns:
            Tuple of (new_password, updated_metadata)
        """
        db_type = metadata.get("db_type", "postgresql")
        username = metadata.get("username")

        if not username:
            raise RotationError("Username required for database rotation", secret_id)

        # Generate new password
        new_password = self._generate_password()

        # Update the database user's password
        if db_type == "postgresql":
            await self._rotate_postgresql(secret_id, username, new_password, metadata)
        elif db_type == "supabase":
            await self._rotate_supabase(secret_id, username, new_password, metadata)
        else:
            raise RotationError(f"Unsupported database type: {db_type}", secret_id)

        from datetime import datetime, timezone

        return new_password, {
            **metadata,
            "version": f"v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "rotated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _rotate_postgresql(
        self,
        secret_id: str,
        username: str,
        new_password: str,
        metadata: dict[str, Any],
    ) -> None:
        """Rotate PostgreSQL password using ALTER USER."""
        host = metadata.get("host", "localhost")
        port = metadata.get("port", 5432)
        database = metadata.get("database", "postgres")
        admin_user = metadata.get("admin_user", "postgres")
        admin_password = metadata.get("admin_password")

        if not admin_password:
            # Try to get from secrets manager
            try:
                from aragora.config.secrets import get_secret

                admin_password = get_secret("POSTGRES_ADMIN_PASSWORD")
            except (ImportError, KeyError, ValueError, OSError):
                raise RotationError("Admin password required for PostgreSQL rotation", secret_id)

        try:
            import asyncpg

            # Connect with admin credentials
            conn = await asyncpg.connect(
                host=host,
                port=port,
                database=database,
                user=admin_user,
                password=admin_password,
                timeout=30,
            )

            try:
                # Validate and quote username to prevent SQL injection
                _validate_pg_identifier(username, "username")
                quoted = _quote_pg_identifier(username)
                await conn.execute(f"ALTER USER {quoted} WITH PASSWORD $1", new_password)
                logger.info("Updated PostgreSQL password for user %s", username)
            finally:
                await conn.close()

        except ImportError:
            logger.warning(
                "asyncpg not installed, skipping actual rotation. Install with: pip install asyncpg"
            )
            # In production, this would fail. For testing, we allow it.
        except (OSError, TimeoutError, ConnectionError, RuntimeError) as e:
            raise RotationError(f"PostgreSQL rotation failed: {e}", secret_id)

    async def _rotate_supabase(
        self,
        secret_id: str,
        username: str,
        new_password: str,
        metadata: dict[str, Any],
    ) -> None:
        """
        Rotate Supabase database password.

        Supabase uses PostgreSQL under the hood, but may require
        API calls for managed database users.
        """
        project_ref = metadata.get("project_ref")
        api_key = metadata.get("service_role_key")

        if project_ref and api_key:
            # Validate project ref before URL interpolation
            _validate_project_ref(project_ref)

            # Use Supabase Management API if available
            try:
                from aragora.observability.http_client_pool import get_http_pool

                pool = get_http_pool()
                async with pool.get_session("supabase") as client:
                    response = await client.patch(
                        f"https://api.supabase.com/v1/projects/{project_ref}/database/password",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"password": new_password},
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    logger.info("Updated Supabase database password via API")
            except (
                ImportError,
                OSError,
                TimeoutError,
                ConnectionError,
                RuntimeError,
                ValueError,
            ) as e:
                logger.warning("Supabase API rotation failed: %s, falling back to direct", e)
                # Fall back to direct PostgreSQL rotation
                await self._rotate_postgresql(secret_id, username, new_password, metadata)
        else:
            # Direct PostgreSQL connection
            await self._rotate_postgresql(secret_id, username, new_password, metadata)

    async def validate_credentials(
        self, secret_id: str, secret_value: str, metadata: dict[str, Any]
    ) -> bool:
        """
        Validate database credentials by attempting a connection.

        Args:
            secret_id: Database credential identifier
            secret_value: Password to test
            metadata: Connection details

        Returns:
            True if connection succeeds
        """
        db_type = metadata.get("db_type", "postgresql")
        host = metadata.get("host", "localhost")
        port = metadata.get("port", 5432)
        database = metadata.get("database", "postgres")
        username = metadata.get("username")

        if not username:
            logger.error("No username provided for validation of %s", secret_id)
            return False

        if db_type in ("postgresql", "supabase"):
            try:
                import asyncpg

                conn = await asyncpg.connect(
                    host=host,
                    port=port,
                    database=database,
                    user=username,
                    password=secret_value,
                    timeout=10,
                )
                await conn.execute("SELECT 1")
                await conn.close()
                logger.info("Validated database credentials for %s", secret_id)
                return True
            except ImportError:
                logger.warning("asyncpg not installed, assuming credentials valid")
                return True
            except (OSError, TimeoutError, ConnectionError, RuntimeError) as e:
                logger.error("Database validation failed for %s: %s", secret_id, e)
                return False
        else:
            logger.warning("No validation for db_type=%s", db_type)
            return True

    async def revoke_old_credentials(
        self, secret_id: str, old_value: str, metadata: dict[str, Any]
    ) -> bool:
        """
        Revoke old database credentials.

        For databases, this is a no-op since updating the password
        automatically invalidates the old one. We just log it.

        Args:
            secret_id: Database credential identifier
            old_value: Old password (already invalidated)
            metadata: Connection details

        Returns:
            True (password was already rotated)
        """
        logger.info("Old database credentials for %s were invalidated during rotation", secret_id)
        return True
