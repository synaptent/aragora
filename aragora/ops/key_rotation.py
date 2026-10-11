"""
Key Rotation Scheduler for Aragora.

Provides automated key rotation with:
- Configurable rotation intervals
- Re-encryption of existing data
- Audit logging of all operations
- Health checks and alerting
- Graceful key overlap periods

Usage:
    from aragora.ops.key_rotation import (
        KeyRotationScheduler,
        KeyRotationConfig,
        get_key_rotation_scheduler,
    )

    # Get the scheduler
    scheduler = get_key_rotation_scheduler()

    # Start automated rotation
    await scheduler.start()

    # Manual rotation
    result = await scheduler.rotate_now()

    # Check rotation status
    status = await scheduler.get_status()

Configuration via environment:
    ARAGORA_KEY_ROTATION_INTERVAL_DAYS: Days between rotations (default: 90)
    ARAGORA_KEY_ROTATION_OVERLAP_DAYS: Days to keep old keys valid (default: 7)
    ARAGORA_KEY_ROTATION_RE_ENCRYPT: Whether to re-encrypt data (default: false)
    ARAGORA_KEY_ROTATION_ALERT_DAYS: Days before rotation to alert (default: 7)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.persistence.db_config import get_default_data_dir

logger = logging.getLogger(__name__)


class RotationStatus(Enum):
    """Key rotation status."""

    IDLE = "idle"
    SCHEDULED = "scheduled"
    ROTATING = "rotating"
    RE_ENCRYPTING = "re_encrypting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class KeyRotationConfig:
    """Configuration for key rotation scheduler."""

    # Rotation interval in days
    rotation_interval_days: int = 90

    # How many days old keys remain valid for decryption
    key_overlap_days: int = 7

    # Whether to re-encrypt existing data with new key
    re_encrypt_on_rotation: bool = False

    # Days before rotation to send alerts
    alert_days_before: int = 7

    # Maximum concurrent re-encryption tasks
    re_encrypt_batch_size: int = 100

    # Re-encryption timeout in seconds
    re_encrypt_timeout: float = 3600.0

    # Stores to re-encrypt on rotation
    stores_to_re_encrypt: list[str] = field(
        default_factory=lambda: [
            "integrations",
            "webhooks",
            "gmail_tokens",
            "enterprise_sync",
        ]
    )

    @classmethod
    def from_env(cls) -> KeyRotationConfig:
        """Create config from environment variables."""
        return cls(
            rotation_interval_days=int(os.environ.get("ARAGORA_KEY_ROTATION_INTERVAL_DAYS", "90")),
            key_overlap_days=int(os.environ.get("ARAGORA_KEY_ROTATION_OVERLAP_DAYS", "7")),
            re_encrypt_on_rotation=os.environ.get(
                "ARAGORA_KEY_ROTATION_RE_ENCRYPT", "false"
            ).lower()
            == "true",
            alert_days_before=int(os.environ.get("ARAGORA_KEY_ROTATION_ALERT_DAYS", "7")),
        )


@dataclass
class KeyRotationResult:
    """Result of a key rotation operation."""

    success: bool
    key_id: str
    old_version: int
    new_version: int
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    records_re_encrypted: int = 0
    re_encryption_errors: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "key_id": self.key_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "records_re_encrypted": self.records_re_encrypted,
            "re_encryption_errors": self.re_encryption_errors,
            "error": self.error,
        }


@dataclass
class RotationSchedule:
    """Information about scheduled rotations."""

    next_rotation: datetime | None = None
    last_rotation: datetime | None = None
    last_result: KeyRotationResult | None = None
    rotation_count: int = 0
    status: RotationStatus = RotationStatus.IDLE


class KeyRotationScheduler:
    """
    Automated key rotation scheduler.

    Manages encryption key lifecycle including:
    - Scheduled automatic rotation
    - Manual rotation triggers
    - Re-encryption of existing data
    - Audit logging
    - Alert notifications
    """

    def __init__(
        self,
        config: KeyRotationConfig | None = None,
        alert_callback: Callable[[str, str, dict], None] | None = None,
    ):
        """
        Initialize the scheduler.

        Args:
            config: Rotation configuration
            alert_callback: Callback for alerts (severity, message, details)
        """
        self.config = config or KeyRotationConfig.from_env()
        self.alert_callback = alert_callback
        self._schedule = RotationSchedule()
        self._task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()

    @property
    def status(self) -> RotationStatus:
        """Get current rotation status."""
        return self._schedule.status

    async def start(self) -> None:
        """Start the automated rotation scheduler."""
        if self._running:
            logger.warning("Key rotation scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "Key rotation scheduler started. Interval: %s days", self.config.rotation_interval_days
        )

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Key rotation scheduler stopped")

    async def get_status(self) -> dict[str, Any]:
        """Get current scheduler status."""
        return {
            "status": self._schedule.status.value,
            "running": self._running,
            "next_rotation": (
                self._schedule.next_rotation.isoformat() if self._schedule.next_rotation else None
            ),
            "last_rotation": (
                self._schedule.last_rotation.isoformat() if self._schedule.last_rotation else None
            ),
            "rotation_count": self._schedule.rotation_count,
            "last_result": (
                self._schedule.last_result.to_dict() if self._schedule.last_result else None
            ),
            "config": {
                "rotation_interval_days": self.config.rotation_interval_days,
                "key_overlap_days": self.config.key_overlap_days,
                "re_encrypt_on_rotation": self.config.re_encrypt_on_rotation,
                "alert_days_before": self.config.alert_days_before,
            },
        }

    async def rotate_now(self, force: bool = False) -> KeyRotationResult:
        """
        Perform key rotation immediately.

        Args:
            force: Force rotation even if not due

        Returns:
            Rotation result
        """
        async with self._lock:
            return await self._perform_rotation()

    async def check_rotation_due(self) -> bool:
        """Check if key rotation is due."""
        try:
            from aragora.security.encryption import get_encryption_service

            service = get_encryption_service()
            active_key = service.get_active_key()

            if not active_key:
                return True  # No key, rotation needed

            key_age_days = (datetime.now(timezone.utc) - active_key.created_at).days

            return key_age_days >= self.config.rotation_interval_days

        except (ImportError, AttributeError, RuntimeError) as e:
            logger.error("Error checking rotation due: %s", e)
            return False

    async def get_key_age_days(self) -> int | None:
        """Get the age of the current active key in days."""
        try:
            from aragora.security.encryption import get_encryption_service

            service = get_encryption_service()
            active_key = service.get_active_key()

            if not active_key:
                return None

            return (datetime.now(timezone.utc) - active_key.created_at).days

        except (ImportError, AttributeError, RuntimeError) as e:
            logger.error("Error getting key age: %s", e)
            return None

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._check_and_rotate()
                await self._check_alerts()

                # Check every hour
                await asyncio.sleep(3600)

            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - Scheduler loop must survive any error to keep running
                logger.error("Error in scheduler loop: %s", e)
                await asyncio.sleep(60)  # Wait before retry

    async def _check_and_rotate(self) -> None:
        """Check if rotation is due and perform it."""
        if await self.check_rotation_due():
            async with self._lock:
                self._schedule.status = RotationStatus.SCHEDULED
                logger.info("Key rotation is due, starting rotation")
                await self._perform_rotation()

    async def _check_alerts(self) -> None:
        """Check if alerts should be sent."""
        key_age = await self.get_key_age_days()
        if key_age is None:
            return

        days_until_rotation = self.config.rotation_interval_days - key_age

        if 0 < days_until_rotation <= self.config.alert_days_before:
            await self._send_alert(
                "warning",
                f"Key rotation due in {days_until_rotation} days",
                {
                    "key_age_days": key_age,
                    "days_until_rotation": days_until_rotation,
                    "rotation_interval_days": self.config.rotation_interval_days,
                },
            )

    async def _perform_rotation(self) -> KeyRotationResult:
        """Perform the key rotation."""
        from aragora.security.encryption import get_encryption_service
        from aragora.observability.security_audit import (
            audit_key_rotation,
            audit_migration_started,
            audit_migration_completed,
        )
        from aragora.observability.metrics.security import (
            record_key_rotation,
            track_migration,
        )

        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()
        self._schedule.status = RotationStatus.ROTATING

        try:
            service = get_encryption_service()
            active_key = service.get_active_key()
            old_version = active_key.version if active_key else 0

            # Perform rotation
            new_key = service.rotate_key()
            new_version = new_key.version

            duration = time.perf_counter() - start_time
            logger.info("Key rotated: %s v%s -> v%s", new_key.key_id, old_version, new_version)

            # Record metrics
            record_key_rotation(new_key.key_id, True, duration)

            # Audit log
            await audit_key_rotation(
                actor="system:key_rotation_scheduler",
                key_id=new_key.key_id,
                old_version=old_version,
                new_version=new_version,
                success=True,
                latency_ms=duration * 1000,
            )

            # Re-encrypt if configured
            records_re_encrypted = 0
            re_encryption_errors: list[str] = []

            if self.config.re_encrypt_on_rotation:
                self._schedule.status = RotationStatus.RE_ENCRYPTING

                await audit_migration_started(
                    actor="system:key_rotation_scheduler",
                    migration_type="re_encrypt_after_rotation",
                    stores=self.config.stores_to_re_encrypt,
                )

                re_start = time.perf_counter()

                for store in self.config.stores_to_re_encrypt:
                    try:
                        with track_migration(store):
                            count = await self._re_encrypt_store(store)
                            records_re_encrypted += count
                            logger.info("Re-encrypted %s records in %s", count, store)
                    except Exception as e:  # noqa: BLE001 - Per-store re-encryption must not abort the overall rotation
                        error = f"{store}: {e}"
                        re_encryption_errors.append(error)
                        logger.error("Error re-encrypting %s: %s", store, e)

                re_duration = time.perf_counter() - re_start

                await audit_migration_completed(
                    actor="system:key_rotation_scheduler",
                    migration_type="re_encrypt_after_rotation",
                    success=len(re_encryption_errors) == 0,
                    records_migrated=records_re_encrypted,
                    errors=re_encryption_errors,
                    duration_seconds=re_duration,
                )

            completed_at = datetime.now(timezone.utc)
            total_duration = time.perf_counter() - start_time

            result = KeyRotationResult(
                success=True,
                key_id=new_key.key_id,
                old_version=old_version,
                new_version=new_version,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=total_duration,
                records_re_encrypted=records_re_encrypted,
                re_encryption_errors=re_encryption_errors,
            )

            self._schedule.last_rotation = completed_at
            self._schedule.last_result = result
            self._schedule.rotation_count += 1
            self._schedule.next_rotation = completed_at + timedelta(
                days=self.config.rotation_interval_days
            )
            self._schedule.status = RotationStatus.COMPLETED

            await self._send_alert(
                "info",
                "Key rotation completed successfully",
                result.to_dict(),
            )

            return result

        except Exception as e:  # noqa: BLE001 - Rotation failure handler must capture any error for audit/alerting
            duration = time.perf_counter() - start_time
            error_msg = str(e)
            logger.error("Key rotation failed: %s", e)

            record_key_rotation("unknown", False, duration)

            await audit_key_rotation(
                actor="system:key_rotation_scheduler",
                key_id="unknown",
                old_version=0,
                new_version=0,
                success=False,
                latency_ms=duration * 1000,
                error=error_msg,
            )

            result = KeyRotationResult(
                success=False,
                key_id="unknown",
                old_version=0,
                new_version=0,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                duration_seconds=duration,
                error=error_msg,
            )

            self._schedule.last_result = result
            self._schedule.status = RotationStatus.FAILED

            await self._send_alert(
                "critical",
                f"Key rotation failed: {error_msg}",
                result.to_dict(),
            )

            return result

    async def _re_encrypt_store(self, store: str) -> int:
        """
        Re-encrypt all records in a store with the new key.

        Args:
            store: Store name

        Returns:
            Number of records re-encrypted
        """

        count = 0

        if store == "integrations":
            count = await self._re_encrypt_integrations()
        elif store == "webhooks":
            count = await self._re_encrypt_webhooks()
        elif store == "gmail_tokens":
            count = await self._re_encrypt_gmail_tokens()
        elif store == "enterprise_sync":
            count = await self._re_encrypt_sync_configs()
        else:
            logger.warning("Unknown store for re-encryption: %s", store)

        return count

    async def _re_encrypt_integrations(self) -> int:
        """Re-encrypt integration store."""
        import json
        import sqlite3

        from aragora.storage.encrypted_fields import (
            decrypt_sensitive,
            encrypt_sensitive,
        )

        data_dir = get_default_data_dir()
        db_path = data_dir / "integrations.db"

        if not db_path.exists():
            return 0

        count = 0
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT id, settings_json FROM integrations WHERE settings_json IS NOT NULL"
            )
            rows = cursor.fetchall()

            for record_id, settings_json in rows:
                if not settings_json:
                    continue

                try:
                    settings = json.loads(settings_json)
                    decrypted = decrypt_sensitive(settings)
                    re_encrypted = encrypt_sensitive(decrypted, record_id=record_id)

                    cursor.execute(
                        "UPDATE integrations SET settings_json = ? WHERE id = ?",
                        (json.dumps(re_encrypted), record_id),
                    )
                    count += 1
                except (json.JSONDecodeError, ValueError, TypeError, KeyError, OSError) as e:
                    logger.error("Error re-encrypting integration %s: %s", record_id, e)

            conn.commit()
        finally:
            conn.close()

        return count

    async def _re_encrypt_webhooks(self) -> int:
        """Re-encrypt webhook store."""
        import sqlite3

        from aragora.security.encryption import get_encryption_service

        data_dir = get_default_data_dir()
        db_path = data_dir / "webhooks.db"

        if not db_path.exists():
            return 0

        count = 0
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        service = get_encryption_service()

        try:
            cursor.execute(
                "SELECT id, secret FROM webhooks WHERE secret IS NOT NULL AND secret != ''"
            )
            rows = cursor.fetchall()

            for webhook_id, secret in rows:
                try:
                    # Decrypt with old key
                    decrypted = service.decrypt_value(secret)

                    # Re-encrypt with new key
                    re_encrypted = service.encrypt(decrypted)

                    cursor.execute(
                        "UPDATE webhooks SET secret = ? WHERE id = ?",
                        (re_encrypted.to_base64(), webhook_id),
                    )
                    count += 1
                except (ValueError, TypeError, KeyError, OSError) as e:
                    logger.error("Error re-encrypting webhook %s: %s", webhook_id, e)

            conn.commit()
        finally:
            conn.close()

        return count

    async def _re_encrypt_gmail_tokens(self) -> int:
        """Re-encrypt Gmail token store."""
        import sqlite3

        from aragora.security.encryption import get_encryption_service

        data_dir = get_default_data_dir()
        db_path = data_dir / "gmail_tokens.db"

        if not db_path.exists():
            return 0

        count = 0
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        service = get_encryption_service()

        try:
            cursor.execute("SELECT user_id, access_token, refresh_token FROM gmail_tokens")
            rows = cursor.fetchall()

            for user_id, access_token, refresh_token in rows:
                try:
                    updates = []
                    params = []

                    if access_token:
                        decrypted = service.decrypt_value(access_token)
                        re_encrypted = service.encrypt(decrypted)
                        updates.append("access_token = ?")
                        params.append(re_encrypted.to_base64())

                    if refresh_token:
                        decrypted = service.decrypt_value(refresh_token)
                        re_encrypted = service.encrypt(decrypted)
                        updates.append("refresh_token = ?")
                        params.append(re_encrypted.to_base64())

                    if updates:
                        params.append(user_id)
                        cursor.execute(
                            f"UPDATE gmail_tokens SET {', '.join(updates)} WHERE user_id = ?",  # noqa: S608 -- dynamic clause from internal state
                            params,
                        )
                        count += 1
                except (ValueError, TypeError, KeyError, OSError) as e:
                    logger.error("Error re-encrypting tokens for %s: %s", user_id, e)

            conn.commit()
        finally:
            conn.close()

        return count

    async def _re_encrypt_sync_configs(self) -> int:
        """Re-encrypt sync config store."""
        import json
        import sqlite3

        from aragora.storage.encrypted_fields import (
            decrypt_sensitive,
            encrypt_sensitive,
        )

        data_dir = get_default_data_dir()
        db_path = data_dir / "enterprise_sync.db"

        if not db_path.exists():
            return 0

        count = 0
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT id, config_json FROM sync_configs WHERE config_json IS NOT NULL")
            rows = cursor.fetchall()

            for config_id, config_json in rows:
                if not config_json:
                    continue

                try:
                    config = json.loads(config_json)
                    decrypted = decrypt_sensitive(config)
                    re_encrypted = encrypt_sensitive(decrypted, record_id=config_id)

                    cursor.execute(
                        "UPDATE sync_configs SET config_json = ? WHERE id = ?",
                        (json.dumps(re_encrypted), config_id),
                    )
                    count += 1
                except (json.JSONDecodeError, ValueError, TypeError, KeyError, OSError) as e:
                    logger.error("Error re-encrypting sync config %s: %s", config_id, e)

            conn.commit()
        finally:
            conn.close()

        return count

    async def _send_alert(
        self,
        severity: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        """Send an alert notification."""
        from aragora.observability.security_audit import audit_security_alert

        logger.log(
            logging.CRITICAL if severity == "critical" else logging.WARNING,
            "[KEY ROTATION] %s: %s",
            severity.upper(),
            message,
        )

        # Audit log the alert
        await audit_security_alert(
            alert_type="key_rotation",
            destination="system_log",
            triggered_by="key_rotation_scheduler",
            severity=severity,
            message=message,
            **details,
        )

        # Call custom callback if provided
        if self.alert_callback:
            try:
                self.alert_callback(severity, message, details)
            except Exception as e:  # noqa: BLE001 - Alert callback failure must not crash the rotation scheduler
                logger.error("Error in alert callback: %s", e)


# Global scheduler instance
_scheduler: KeyRotationScheduler | None = None


def get_key_rotation_scheduler() -> KeyRotationScheduler:
    """Get the global key rotation scheduler instance."""
    global _scheduler

    if _scheduler is None:
        _scheduler = KeyRotationScheduler()

    return _scheduler


def reset_key_rotation_scheduler() -> None:
    """Reset the global scheduler instance (for testing)."""
    global _scheduler
    _scheduler = None
