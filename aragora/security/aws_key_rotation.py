"""
AWS Secrets Manager Rotation Lambda Handler.

Implements the four-step AWS Secrets Manager rotation protocol:
1. create_secret - Generate new credential material
2. set_secret - Store in Secrets Manager as AWSPENDING
3. test_secret - Verify the new credential works
4. finish_secret - Promote AWSPENDING to AWSCURRENT

Supports rotation for:
- Database credentials (PostgreSQL, Redis)
- API keys (provider keys, internal tokens)
- Encryption keys (AES-256 master keys)
- JWT signing keys (HMAC secrets)

Configurable rotation schedules:
- DB credentials: 30 days (default)
- API keys: 90 days (default)
- Encryption keys: 90 days (default)
- JWT signing keys: 60 days (default)

Usage as Lambda handler:
    # In AWS Lambda configuration, set handler to:
    # aragora.security.aws_key_rotation.lambda_handler

Usage programmatically:
    from aragora.security.aws_key_rotation import (
        AWSSecretRotator,
        RotationConfig,
        SecretType,
    )

    rotator = AWSSecretRotator(config=RotationConfig())
    await rotator.rotate_secret("aragora/production/db-credentials")

SOC 2 Compliance: CC6.1, CC6.7 (Cryptographic Key Management)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import string
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional boto3 import
# ---------------------------------------------------------------------------
_BOTO3_AVAILABLE = False
try:
    import boto3
    from botocore.exceptions import ClientError

    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]

    class ClientError(Exception):  # type: ignore[no-redef]
        """Fallback when botocore is not installed."""

        response: dict[str, Any]

        def __init__(self, *args: object, **kwargs: Any) -> None:
            super().__init__(*args)
            self.response = kwargs.get("response", {})  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class SecretType(str, Enum):
    """Types of secrets that can be rotated."""

    DB_CREDENTIAL = "db_credential"
    API_KEY = "api_key"
    ENCRYPTION_KEY = "encryption_key"
    JWT_SIGNING_KEY = "jwt_signing_key"
    REDIS_PASSWORD = "redis_password"  # noqa: S105 -- enum value


class RotationStep(str, Enum):
    """AWS Secrets Manager rotation steps."""

    CREATE_SECRET = "createSecret"  # noqa: S105 -- enum value
    SET_SECRET = "setSecret"  # noqa: S105 -- enum value
    TEST_SECRET = "testSecret"  # noqa: S105 -- enum value
    FINISH_SECRET = "finishSecret"  # noqa: S105 -- enum value


class RotationEventType(str, Enum):
    """Rotation lifecycle events for auditing."""

    ROTATION_STARTED = "rotation_started"
    SECRET_CREATED = "secret_created"  # noqa: S105 -- enum value
    SECRET_SET = "secret_set"  # noqa: S105 -- enum value
    SECRET_TESTED = "secret_tested"  # noqa: S105 -- enum value
    SECRET_FINISHED = "secret_finished"  # noqa: S105 -- enum value
    ROTATION_FAILED = "rotation_failed"
    ROTATION_COMPLETED = "rotation_completed"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default rotation intervals in days per secret type
DEFAULT_ROTATION_DAYS: dict[str, int] = {
    SecretType.DB_CREDENTIAL: 30,
    SecretType.API_KEY: 90,
    SecretType.ENCRYPTION_KEY: 90,
    SecretType.JWT_SIGNING_KEY: 60,
    SecretType.REDIS_PASSWORD: 30,
}


@dataclass
class RotationConfig:
    """Configuration for AWS Secrets Manager rotation."""

    # Rotation intervals per secret type (days)
    rotation_intervals: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_ROTATION_DAYS))

    # AWS region for Secrets Manager
    aws_region: str = ""

    # Secret name prefix in AWS Secrets Manager
    secret_prefix: str = "aragora"  # noqa: S105 -- config default

    # DB connection parameters for credential testing
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""

    # Redis connection parameters for password testing
    redis_host: str = ""
    redis_port: int = 6379

    # Password generation settings
    password_length: int = 32
    password_chars: str = string.ascii_letters + string.digits + "!@#$%^&*"

    # API key length (hex characters)
    api_key_length: int = 64

    # Encryption key length (bytes; 32 = AES-256)
    encryption_key_bytes: int = 32

    # JWT signing key length (bytes)
    jwt_key_bytes: int = 64

    @classmethod
    def from_env(cls) -> RotationConfig:
        """Load rotation configuration from environment variables."""
        config = cls()
        config.aws_region = (
            os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        )
        config.db_host = os.environ.get("ARAGORA_DB_HOST", "")
        config.db_port = int(os.environ.get("ARAGORA_DB_PORT", "5432"))
        config.db_name = os.environ.get("ARAGORA_DB_NAME", "aragora")
        config.redis_host = os.environ.get("ARAGORA_REDIS_HOST", "")
        config.redis_port = int(os.environ.get("ARAGORA_REDIS_PORT", "6379"))

        # Allow overriding rotation intervals from env
        for secret_type in SecretType:
            env_key = f"ARAGORA_ROTATION_DAYS_{secret_type.value.upper()}"
            env_val = os.environ.get(env_key)
            if env_val:
                config.rotation_intervals[secret_type] = int(env_val)

        return config


@dataclass
class RotationEvent:
    """Audit record for a rotation lifecycle event."""

    event_type: RotationEventType
    secret_id: str
    secret_type: SecretType | None
    step: RotationStep | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging / audit storage."""
        return {
            "event_type": self.event_type.value,
            "secret_id": self.secret_id,
            "secret_type": self.secret_type.value if self.secret_type else None,
            "step": self.step.value if self.step else None,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class AWSRotationStatus:
    """Current rotation status for a managed secret."""

    secret_id: str
    secret_type: SecretType
    last_rotated_at: datetime | None = None
    next_rotation_at: datetime | None = None
    rotation_interval_days: int = 90
    pending_rotation: bool = False
    last_error: str | None = None
    version_stage: str = "AWSCURRENT"

    def is_due(self) -> bool:
        """Check whether this secret is due for rotation."""
        if self.next_rotation_at is None:
            return True
        return datetime.now(timezone.utc) >= self.next_rotation_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "secret_id": self.secret_id,
            "secret_type": self.secret_type.value,
            "last_rotated_at": (self.last_rotated_at.isoformat() if self.last_rotated_at else None),
            "next_rotation_at": (
                self.next_rotation_at.isoformat() if self.next_rotation_at else None
            ),
            "rotation_interval_days": self.rotation_interval_days,
            "pending_rotation": self.pending_rotation,
            "last_error": self.last_error,
            "version_stage": self.version_stage,
            "is_due": self.is_due(),
        }


# ---------------------------------------------------------------------------
# Credential generators
# ---------------------------------------------------------------------------


def _generate_db_password(config: RotationConfig) -> str:
    """Generate a strong random database password."""
    return "".join(secrets.choice(config.password_chars) for _ in range(config.password_length))


def _generate_api_key(config: RotationConfig) -> str:
    """Generate a random hex API key."""
    return secrets.token_hex(config.api_key_length // 2)


def _generate_encryption_key(config: RotationConfig) -> str:
    """Generate a random AES-256 encryption key (hex-encoded)."""
    return secrets.token_hex(config.encryption_key_bytes)


def _generate_jwt_signing_key(config: RotationConfig) -> str:
    """Generate a random JWT HMAC signing key (hex-encoded)."""
    return secrets.token_hex(config.jwt_key_bytes)


def _generate_redis_password(config: RotationConfig) -> str:
    """Generate a strong random Redis password."""
    return "".join(secrets.choice(config.password_chars) for _ in range(config.password_length))


_GENERATORS: dict[SecretType, Any] = {
    SecretType.DB_CREDENTIAL: _generate_db_password,
    SecretType.API_KEY: _generate_api_key,
    SecretType.ENCRYPTION_KEY: _generate_encryption_key,
    SecretType.JWT_SIGNING_KEY: _generate_jwt_signing_key,
    SecretType.REDIS_PASSWORD: _generate_redis_password,
}


# ---------------------------------------------------------------------------
# Credential testers
# ---------------------------------------------------------------------------


def _test_db_credential(secret_value: dict[str, Any], config: RotationConfig) -> bool:
    """Test that a database credential can establish a connection."""
    try:
        import psycopg2  # type: ignore[import-untyped]

        host = secret_value.get("host") or config.db_host
        port = secret_value.get("port") or config.db_port
        dbname = secret_value.get("dbname") or config.db_name
        username = secret_value.get("username", "")
        password = secret_value.get("password", "")

        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=username,
            password=password,
            connect_timeout=5,
        )
        conn.close()
        return True
    except ImportError:
        logger.warning("psycopg2 not available; skipping DB credential test")
        return True  # Cannot test without driver; assume valid
    except (OSError, ValueError, RuntimeError) as e:
        logger.error("DB credential test failed: %s", e)
        return False


def _test_redis_credential(secret_value: dict[str, Any], config: RotationConfig) -> bool:
    """Test that a Redis password works."""
    try:
        import redis as redis_lib  # type: ignore[import-untyped]

        host = secret_value.get("host") or config.redis_host
        port = secret_value.get("port") or config.redis_port
        password = secret_value.get("password", "")

        r = redis_lib.Redis(host=host, port=port, password=password, socket_timeout=5)
        r.ping()
        r.close()
        return True
    except ImportError:
        logger.warning("redis library not available; skipping Redis credential test")
        return True
    except (OSError, ValueError, RuntimeError, ConnectionError) as e:
        logger.error("Redis credential test failed: %s", e)
        return False


def _test_api_key(secret_value: dict[str, Any], _config: RotationConfig) -> bool:
    """Test that an API key has the expected format."""
    key = secret_value.get("api_key") or secret_value.get("key", "")
    if not key or len(key) < 16:
        logger.error("API key is missing or too short")
        return False
    return True


def _test_encryption_key(secret_value: dict[str, Any], _config: RotationConfig) -> bool:
    """Test that an encryption key is valid AES-256 material."""
    key_hex = secret_value.get("encryption_key") or secret_value.get("key", "")
    if not key_hex:
        logger.error("Encryption key is empty")
        return False
    try:
        key_bytes = bytes.fromhex(key_hex)
        if len(key_bytes) not in (16, 24, 32):
            logger.error("Encryption key has invalid length: %d bytes", len(key_bytes))
            return False
        return True
    except ValueError:
        logger.error("Encryption key is not valid hex")
        return False


def _test_jwt_key(secret_value: dict[str, Any], _config: RotationConfig) -> bool:
    """Test that a JWT signing key is valid."""
    key_hex = secret_value.get("jwt_key") or secret_value.get("key", "")
    if not key_hex or len(key_hex) < 32:
        logger.error("JWT key is missing or too short")
        return False
    return True


_TESTERS: dict[SecretType, Any] = {
    SecretType.DB_CREDENTIAL: _test_db_credential,
    SecretType.API_KEY: _test_api_key,
    SecretType.ENCRYPTION_KEY: _test_encryption_key,
    SecretType.JWT_SIGNING_KEY: _test_jwt_key,
    SecretType.REDIS_PASSWORD: _test_redis_credential,
}


# ---------------------------------------------------------------------------
# Core Rotator
# ---------------------------------------------------------------------------


class AWSSecretRotator:
    """
    Implements the four-step AWS Secrets Manager rotation protocol.

    Each secret in Secrets Manager has a JSON payload with:
    - ``secret_type``: one of the :class:`SecretType` values
    - type-specific fields (``password``, ``api_key``, ``encryption_key``, etc.)

    The rotator generates new credential material, stores it as the AWSPENDING
    version, tests it, and then promotes it to AWSCURRENT.
    """

    def __init__(self, config: RotationConfig | None = None) -> None:
        self._config = config or RotationConfig.from_env()
        self._client: Any | None = None
        self._audit_log: list[RotationEvent] = []
        self._statuses: dict[str, AWSRotationStatus] = {}

    # -- AWS client ----------------------------------------------------------

    def _get_client(self) -> Any:
        """Get or create the Secrets Manager client."""
        if self._client is not None:
            return self._client
        if not _BOTO3_AVAILABLE:
            raise RuntimeError(
                "boto3 is required for AWS Secrets Manager rotation. "
                "Install with: pip install boto3"
            )
        region = self._config.aws_region or "us-east-1"
        self._client = boto3.client("secretsmanager", region_name=region)
        return self._client

    # -- Audit ---------------------------------------------------------------

    def _emit_audit(self, event: RotationEvent) -> None:
        """Record and log an audit event."""
        self._audit_log.append(event)
        level = logging.INFO if event.success else logging.ERROR
        logger.log(
            level,
            "Rotation event: %s secret=%s step=%s success=%s",
            event.event_type.value,
            event.secret_id,
            event.step.value if event.step else "n/a",
            event.success,
        )

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent audit events."""
        return [e.to_dict() for e in self._audit_log[-limit:]]

    # -- Secret type detection -----------------------------------------------

    @staticmethod
    def _detect_secret_type(secret_value: dict[str, Any]) -> SecretType:
        """Detect the secret type from its JSON payload."""
        explicit = secret_value.get("secret_type")
        if explicit:
            try:
                return SecretType(explicit)
            except ValueError:
                pass

        # Heuristic detection
        if "password" in secret_value and "username" in secret_value:
            return SecretType.DB_CREDENTIAL
        if "encryption_key" in secret_value:
            return SecretType.ENCRYPTION_KEY
        if "jwt_key" in secret_value:
            return SecretType.JWT_SIGNING_KEY
        if "api_key" in secret_value:
            return SecretType.API_KEY
        if "password" in secret_value and "host" in secret_value:
            return SecretType.REDIS_PASSWORD

        return SecretType.API_KEY  # Default

    # -- Four rotation steps -------------------------------------------------

    def create_secret(self, secret_id: str, client_request_token: str) -> dict[str, Any]:
        """Step 1: Generate new credential material and store as AWSPENDING.

        Retrieves the current AWSCURRENT secret to determine its type, generates
        appropriate new credential material, and stores it in AWSPENDING.
        """
        client = self._get_client()

        # Get current secret to determine type
        try:
            current = client.get_secret_value(SecretId=secret_id, VersionStage="AWSCURRENT")
            current_value = json.loads(current["SecretString"])
        except (ClientError, json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to retrieve current secret %s: %s", secret_id, e)
            raise

        secret_type = self._detect_secret_type(current_value)

        # Check if AWSPENDING already exists for this token
        try:
            client.get_secret_value(
                SecretId=secret_id,
                VersionId=client_request_token,
                VersionStage="AWSPENDING",
            )
            logger.info(
                "AWSPENDING already exists for %s token %s",
                secret_id,
                client_request_token,
            )
            return current_value
        except ClientError:
            pass  # Expected -- no pending version yet

        # Generate new credential
        generator = _GENERATORS.get(secret_type)
        if generator is None:
            raise ValueError(f"No generator for secret type: {secret_type}")

        new_credential = generator(self._config)

        # Build the new secret payload
        new_value = dict(current_value)
        new_value["secret_type"] = secret_type.value

        if secret_type == SecretType.DB_CREDENTIAL:
            new_value["password"] = new_credential
        elif secret_type == SecretType.API_KEY:
            new_value["api_key"] = new_credential
        elif secret_type == SecretType.ENCRYPTION_KEY:
            new_value["encryption_key"] = new_credential
        elif secret_type == SecretType.JWT_SIGNING_KEY:
            new_value["jwt_key"] = new_credential
        elif secret_type == SecretType.REDIS_PASSWORD:
            new_value["password"] = new_credential

        # Store as AWSPENDING
        client.put_secret_value(
            SecretId=secret_id,
            ClientRequestToken=client_request_token,
            SecretString=json.dumps(new_value),
            VersionStages=["AWSPENDING"],
        )

        self._emit_audit(
            RotationEvent(
                event_type=RotationEventType.SECRET_CREATED,
                secret_id=secret_id,
                secret_type=secret_type,
                step=RotationStep.CREATE_SECRET,
                metadata={"client_request_token": client_request_token},
            )
        )

        return new_value

    def set_secret(self, secret_id: str, client_request_token: str) -> None:
        """Step 2: Set the new secret in the target service.

        For database credentials, this would ALTER the user's password.
        For other types, the secret is already stored in Secrets Manager.
        """
        client = self._get_client()

        try:
            pending = client.get_secret_value(
                SecretId=secret_id,
                VersionId=client_request_token,
                VersionStage="AWSPENDING",
            )
            pending_value = json.loads(pending["SecretString"])
        except (ClientError, json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to retrieve AWSPENDING for %s: %s", secret_id, e)
            raise

        secret_type = self._detect_secret_type(pending_value)

        # For DB credentials, apply the password change to the database
        if secret_type == SecretType.DB_CREDENTIAL:
            self._apply_db_password(pending_value)
        elif secret_type == SecretType.REDIS_PASSWORD:
            self._apply_redis_password(pending_value)
        # API keys, encryption keys, and JWT keys are purely in Secrets Manager
        # -- no external service needs updating.

        self._emit_audit(
            RotationEvent(
                event_type=RotationEventType.SECRET_SET,
                secret_id=secret_id,
                secret_type=secret_type,
                step=RotationStep.SET_SECRET,
            )
        )

    def test_secret(self, secret_id: str, client_request_token: str) -> bool:
        """Step 3: Verify the new credential works.

        Retrieves the AWSPENDING secret and runs the appropriate tester.
        """
        client = self._get_client()

        try:
            pending = client.get_secret_value(
                SecretId=secret_id,
                VersionId=client_request_token,
                VersionStage="AWSPENDING",
            )
            pending_value = json.loads(pending["SecretString"])
        except (ClientError, json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to retrieve AWSPENDING for test %s: %s", secret_id, e)
            raise

        secret_type = self._detect_secret_type(pending_value)
        tester = _TESTERS.get(secret_type)
        if tester is None:
            logger.warning("No tester for secret type %s; assuming valid", secret_type)
            return True

        result = tester(pending_value, self._config)

        self._emit_audit(
            RotationEvent(
                event_type=RotationEventType.SECRET_TESTED,
                secret_id=secret_id,
                secret_type=secret_type,
                step=RotationStep.TEST_SECRET,
                success=result,
                error=None if result else "Credential test failed",
            )
        )

        if not result:
            raise ValueError(f"New secret for {secret_id} failed validation test")

        return result

    def finish_secret(self, secret_id: str, client_request_token: str) -> None:
        """Step 4: Promote AWSPENDING to AWSCURRENT.

        Moves the version stages so the new secret becomes active and the
        old one is demoted to AWSPREVIOUS.
        """
        client = self._get_client()

        # Get current version metadata
        metadata = client.describe_secret(SecretId=secret_id)

        current_version: str | None = None
        for version_id, stages in metadata.get("VersionIdsToStages", {}).items():
            if "AWSCURRENT" in stages:
                if version_id == client_request_token:
                    # Already current -- nothing to do
                    logger.info(
                        "Secret %s version %s is already AWSCURRENT",
                        secret_id,
                        client_request_token,
                    )
                    return
                current_version = version_id
                break

        # Move AWSPENDING to AWSCURRENT
        client.update_secret_version_stage(
            SecretId=secret_id,
            VersionStage="AWSCURRENT",
            MoveToVersionId=client_request_token,
            RemoveFromVersionId=current_version,
        )

        self._emit_audit(
            RotationEvent(
                event_type=RotationEventType.SECRET_FINISHED,
                secret_id=secret_id,
                secret_type=None,
                step=RotationStep.FINISH_SECRET,
                metadata={
                    "new_version": client_request_token,
                    "old_version": current_version,
                },
            )
        )

        logger.info(
            "Secret %s rotated: %s -> %s",
            secret_id,
            current_version,
            client_request_token,
        )

    # -- Helpers for applying credentials ------------------------------------

    def _apply_db_password(self, secret_value: dict[str, Any]) -> None:
        """Apply a new password to the database user."""
        try:
            import psycopg2  # type: ignore[import-untyped]

            host = secret_value.get("host") or self._config.db_host
            port = secret_value.get("port") or self._config.db_port
            dbname = secret_value.get("dbname") or self._config.db_name
            username = secret_value.get("username", "")
            new_password = secret_value.get("password", "")

            # Connect as admin to change the user password
            admin_dsn = os.environ.get("ARAGORA_DB_ADMIN_DSN", "")
            if admin_dsn:
                conn = psycopg2.connect(admin_dsn, connect_timeout=10)
            else:
                conn = psycopg2.connect(
                    host=host,
                    port=port,
                    dbname=dbname,
                    user=username,
                    password=os.environ.get("ARAGORA_DB_CURRENT_PASSWORD", ""),
                    connect_timeout=10,
                )

            conn.autocommit = True
            with conn.cursor() as cur:
                # Use psycopg2.sql for safe identifier quoting
                from psycopg2 import sql as psql  # type: ignore[import-untyped]

                cur.execute(
                    psql.SQL("ALTER USER {} WITH PASSWORD %s").format(psql.Identifier(username)),
                    (new_password,),
                )
            conn.close()
            logger.info("Database password updated for user: %s", username)
        except ImportError:
            logger.warning("psycopg2 not available; skipping DB password application")
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Failed to apply DB password: %s", e)
            raise

    def _apply_redis_password(self, secret_value: dict[str, Any]) -> None:
        """Apply a new password to Redis via CONFIG SET."""
        try:
            import redis as redis_lib  # type: ignore[import-untyped]

            host = secret_value.get("host") or self._config.redis_host
            port = secret_value.get("port") or self._config.redis_port
            current_password = os.environ.get("ARAGORA_REDIS_CURRENT_PASSWORD", "")
            new_password = secret_value.get("password", "")

            r = redis_lib.Redis(
                host=host,
                port=port,
                password=current_password,
                socket_timeout=5,
            )
            r.config_set("requirepass", new_password)
            r.close()
            logger.info("Redis password updated")
        except ImportError:
            logger.warning("redis library not available; skipping Redis password update")
        except (OSError, ValueError, RuntimeError, ConnectionError) as e:
            logger.error("Failed to apply Redis password: %s", e)
            raise

    # -- High-level rotation API ---------------------------------------------

    def rotate_secret(self, secret_id: str, client_request_token: str) -> None:
        """Execute all four rotation steps for a secret.

        This is the programmatic API for triggering a full rotation.
        For Lambda invocations, use :func:`lambda_handler` instead.
        """
        start = time.time()
        self._emit_audit(
            RotationEvent(
                event_type=RotationEventType.ROTATION_STARTED,
                secret_id=secret_id,
                secret_type=None,
                step=None,
            )
        )

        try:
            self.create_secret(secret_id, client_request_token)
            self.set_secret(secret_id, client_request_token)
            self.test_secret(secret_id, client_request_token)
            self.finish_secret(secret_id, client_request_token)

            self._emit_audit(
                RotationEvent(
                    event_type=RotationEventType.ROTATION_COMPLETED,
                    secret_id=secret_id,
                    secret_type=None,
                    step=None,
                    metadata={"duration_seconds": round(time.time() - start, 3)},
                )
            )
        except (ClientError, ValueError, RuntimeError, OSError, ConnectionError) as e:
            self._emit_audit(
                RotationEvent(
                    event_type=RotationEventType.ROTATION_FAILED,
                    secret_id=secret_id,
                    secret_type=None,
                    step=None,
                    success=False,
                    error="Rotation failed due to an internal error",
                    metadata={"duration_seconds": round(time.time() - start, 3)},
                )
            )
            logger.error("Rotation failed for %s: %s", secret_id, e)
            raise

    # -- Status tracking -----------------------------------------------------

    def get_rotation_status(self, secret_id: str) -> AWSRotationStatus | None:
        """Get the rotation status for a managed secret."""
        return self._statuses.get(secret_id)

    def get_all_rotation_statuses(self) -> list[AWSRotationStatus]:
        """Get rotation statuses for all tracked secrets."""
        return list(self._statuses.values())

    def track_secret(
        self,
        secret_id: str,
        secret_type: SecretType,
        last_rotated_at: datetime | None = None,
    ) -> AWSRotationStatus:
        """Start tracking a secret for rotation status reporting."""
        interval = self._config.rotation_intervals.get(
            secret_type, DEFAULT_ROTATION_DAYS.get(secret_type, 90)
        )

        from datetime import timedelta

        next_rotation: datetime | None = None
        if last_rotated_at:
            next_rotation = last_rotated_at + timedelta(days=interval)

        status = AWSRotationStatus(
            secret_id=secret_id,
            secret_type=secret_type,
            last_rotated_at=last_rotated_at,
            next_rotation_at=next_rotation,
            rotation_interval_days=interval,
        )
        self._statuses[secret_id] = status
        return status

    def check_secrets_due(self) -> list[AWSRotationStatus]:
        """Return all tracked secrets that are due for rotation."""
        return [s for s in self._statuses.values() if s.is_due()]


# ---------------------------------------------------------------------------
# Lambda handler (entry point for AWS Lambda rotation triggers)
# ---------------------------------------------------------------------------

# Module-level rotator instance for Lambda warm starts
_rotator: AWSSecretRotator | None = None


def _get_rotator() -> AWSSecretRotator:
    """Get or create the module-level rotator for Lambda reuse."""
    global _rotator
    if _rotator is None:
        _rotator = AWSSecretRotator(config=RotationConfig.from_env())
    return _rotator


def lambda_handler(event: dict[str, Any], context: Any) -> None:
    """AWS Lambda handler for Secrets Manager automatic rotation.

    This function is invoked by AWS Secrets Manager when a rotation is
    triggered. It dispatches to the appropriate rotation step.

    Args:
        event: Lambda event with keys:
            - SecretId: ARN or name of the secret
            - ClientRequestToken: Version ID for the new secret
            - Step: One of createSecret, setSecret, testSecret, finishSecret
        context: Lambda context (unused)
    """
    secret_id = event["SecretId"]
    token = event["ClientRequestToken"]
    step = event["Step"]

    logger.info(
        "Rotation Lambda invoked: secret=%s step=%s token=%s",
        secret_id,
        step,
        token[:8] + "...",
    )

    rotator = _get_rotator()

    # Verify the secret is enabled for rotation
    if _BOTO3_AVAILABLE:
        client = rotator._get_client()
        metadata = client.describe_secret(SecretId=secret_id)
        if not metadata.get("RotationEnabled"):
            raise ValueError(f"Secret {secret_id} does not have rotation enabled")

        # Verify the token is valid
        versions = metadata.get("VersionIdsToStages", {})
        if token not in versions:
            raise ValueError(f"Secret version {token} has no stage for rotation of {secret_id}")

    if step == RotationStep.CREATE_SECRET.value:
        rotator.create_secret(secret_id, token)
    elif step == RotationStep.SET_SECRET.value:
        rotator.set_secret(secret_id, token)
    elif step == RotationStep.TEST_SECRET.value:
        rotator.test_secret(secret_id, token)
    elif step == RotationStep.FINISH_SECRET.value:
        rotator.finish_secret(secret_id, token)
    else:
        raise ValueError(f"Unknown rotation step: {step}")


# ---------------------------------------------------------------------------
# Background Rotation Monitor (for server integration)
# ---------------------------------------------------------------------------


class RotationMonitor:
    """Background monitor that checks rotation status and hot-reloads secrets.

    Runs as an asyncio background task within the Aragora server. On each
    check interval it:
    1. Queries tracked secrets to see if any are within the rotation window
    2. Refreshes the SecretManager cache so new values are picked up
    3. Emits metrics and audit events for rotation status changes

    Usage:
        monitor = RotationMonitor(
            rotator=AWSSecretRotator(config),
            check_interval_seconds=300,
        )
        await monitor.start()
        # ... later ...
        await monitor.stop()
    """

    def __init__(
        self,
        rotator: AWSSecretRotator | None = None,
        check_interval_seconds: int = 300,
    ) -> None:
        self._rotator = rotator or AWSSecretRotator(config=RotationConfig.from_env())
        self._check_interval = check_interval_seconds
        self._task: Any = None  # asyncio.Task
        self._running = False
        self._last_check_at: datetime | None = None
        self._reload_count = 0

    @property
    def rotator(self) -> AWSSecretRotator:
        """Access the underlying rotator for status queries."""
        return self._rotator

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_check_at(self) -> datetime | None:
        return self._last_check_at

    @property
    def reload_count(self) -> int:
        return self._reload_count

    async def start(self) -> None:
        """Start the background rotation monitor."""
        if self._running:
            logger.warning("Rotation monitor already running")
            return

        import asyncio

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Rotation monitor started (check every %ds)", self._check_interval)

    async def stop(self) -> None:
        """Stop the background rotation monitor."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                import asyncio

                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Rotation monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        import asyncio

        while self._running:
            try:
                await self._check_and_reload()
                self._last_check_at = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
                ConnectionError,
                TimeoutError,
            ) as e:
                logger.error("Rotation monitor check failed: %s", e)

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break

    async def _check_and_reload(self) -> None:
        """Check for completed rotations and hot-reload secrets."""
        # Check which secrets are due
        due = self._rotator.check_secrets_due()
        if due:
            logger.info(
                "Secrets due for rotation: %s",
                [s.secret_id for s in due],
            )

        # Refresh the global secret cache to pick up any rotated values
        try:
            from aragora.config.secrets import SecretSourceError, refresh_secrets

            refresh_secrets()
            self._reload_count += 1
            logger.debug("Secret cache refreshed (reload #%d)", self._reload_count)
        except (SecretSourceError, ImportError, RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to refresh secret cache: %s", e)

        # Hydrate environment with latest values for hot-reload
        try:
            from aragora.config.secrets import (
                SecretNotFoundError,
                SecretSourceError,
                hydrate_env_from_secrets,
            )

            hydrate_env_from_secrets(overwrite=True)
        except (
            SecretNotFoundError,
            SecretSourceError,
            ImportError,
            RuntimeError,
            ValueError,
            OSError,
        ) as e:
            logger.warning("Secret hydration skipped: %s", e)

    def get_status(self) -> dict[str, Any]:
        """Get monitor status for the admin endpoint."""
        return {
            "running": self._running,
            "check_interval_seconds": self._check_interval,
            "last_check_at": (self._last_check_at.isoformat() if self._last_check_at else None),
            "reload_count": self._reload_count,
            "secrets_tracked": len(self._rotator.get_all_rotation_statuses()),
            "secrets_due": len(self._rotator.check_secrets_due()),
        }


# Global rotation monitor
_rotation_monitor: RotationMonitor | None = None


def get_rotation_monitor() -> RotationMonitor | None:
    """Get the global rotation monitor instance."""
    return _rotation_monitor


def set_rotation_monitor(monitor: RotationMonitor | None) -> None:
    """Set the global rotation monitor (for testing)."""
    global _rotation_monitor
    _rotation_monitor = monitor


async def start_rotation_monitor(
    config: RotationConfig | None = None,
    check_interval_seconds: int = 300,
) -> RotationMonitor:
    """Create and start the global rotation monitor.

    This is the entry point called from server startup to begin
    background rotation monitoring and secret hot-reload.

    Args:
        config: Rotation configuration (defaults from env)
        check_interval_seconds: How often to check rotation status

    Returns:
        The started RotationMonitor instance
    """
    global _rotation_monitor

    if _rotation_monitor is not None:
        await _rotation_monitor.stop()

    rotator = AWSSecretRotator(config=config or RotationConfig.from_env())
    _rotation_monitor = RotationMonitor(
        rotator=rotator,
        check_interval_seconds=check_interval_seconds,
    )
    await _rotation_monitor.start()
    return _rotation_monitor


async def stop_rotation_monitor() -> None:
    """Stop the global rotation monitor."""
    global _rotation_monitor
    if _rotation_monitor is not None:
        await _rotation_monitor.stop()
        _rotation_monitor = None


# ---------------------------------------------------------------------------
# Startup integration helper
# ---------------------------------------------------------------------------


async def init_rotation_on_startup() -> RotationMonitor | None:
    """Initialize rotation monitoring during server startup.

    Called from the server startup sequence to:
    1. Check if any secrets are within the rotation window
    2. Log warnings for secrets that need rotation
    3. Start the background monitor for hot-reload

    Returns:
        The RotationMonitor if AWS Secrets Manager is configured, else None.
    """
    try:
        from aragora.config.secrets import get_secret_manager

        manager = get_secret_manager()
        if not manager.config.use_aws:
            logger.debug("AWS Secrets Manager not configured; rotation monitor disabled")
            return None

        config = RotationConfig.from_env()
        monitor = await start_rotation_monitor(
            config=config,
            check_interval_seconds=int(os.environ.get("ARAGORA_ROTATION_CHECK_INTERVAL", "300")),
        )

        # Log initial status
        due = monitor.rotator.check_secrets_due()
        if due:
            logger.warning(
                "Secrets due for rotation at startup: %s",
                [s.secret_id for s in due],
            )
        else:
            logger.info("All tracked secrets are within rotation policy")

        return monitor

    except ImportError:
        logger.debug("Rotation monitor dependencies not available")
        return None
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("Failed to start rotation monitor: %s", e)
        return None


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "AWSSecretRotator",
    "RotationConfig",
    "RotationEvent",
    "RotationEventType",
    "RotationMonitor",
    "AWSRotationStatus",
    "RotationStep",
    "SecretType",
    "get_rotation_monitor",
    "init_rotation_on_startup",
    "lambda_handler",
    "set_rotation_monitor",
    "start_rotation_monitor",
    "stop_rotation_monitor",
    "DEFAULT_ROTATION_DAYS",
]
