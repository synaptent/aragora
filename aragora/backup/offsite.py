"""
Offsite Backup Automation and Restore Drill Evidence.

Provides cloud-based backup management with:
- Multi-provider support (S3, GCS, Azure Blob)
- Upload/download with checksum verification
- Automated restore drills with evidence collection
- Backup integrity verification
- Drill history for compliance auditing

SOC 2 Compliance: CC9.1, CC9.2 (Business Continuity)

Usage:
    from aragora.backup.offsite import OffsiteBackupManager, OffsiteBackupConfig

    config = OffsiteBackupConfig(
        provider="s3",
        bucket="my-backups",
        prefix="aragora/prod",
        retention_days=90,
    )
    manager = OffsiteBackupManager(config)

    # Upload a local backup
    record = manager.upload_backup("/path/to/backup.db.gz", {"source": "production"})

    # Run a restore drill
    result = manager.run_restore_drill(record.id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class OffsiteBackupConfig:
    """Configuration for offsite backup storage."""

    provider: Literal["s3", "gcs", "azure"]
    bucket: str
    prefix: str = "aragora/backups"
    encryption_key_id: str | None = None
    retention_days: int = 90
    schedule_cron: str = "0 3 * * *"  # 3 AM daily default
    region: str | None = None
    endpoint_url: str | None = None


@dataclass
class OffsiteBackupRecord:
    """Record of an offsite backup."""

    id: str
    timestamp: datetime
    size_bytes: int
    checksum: str
    provider: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "provider": self.provider,
            "path": self.path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OffsiteBackupRecord:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            size_bytes=data["size_bytes"],
            checksum=data["checksum"],
            provider=data["provider"],
            path=data["path"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class RestoreDrillResult:
    """Result of a restore drill."""

    drill_id: str
    backup_id: str
    started_at: datetime
    completed_at: datetime | None = None
    success: bool = False
    duration_seconds: float = 0.0
    tables_verified: int = 0
    rows_verified: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "drill_id": self.drill_id,
            "backup_id": self.backup_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "tables_verified": self.tables_verified,
            "rows_verified": self.rows_verified,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestoreDrillResult:
        """Create from dictionary."""
        return cls(
            drill_id=data["drill_id"],
            backup_id=data["backup_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            success=data.get("success", False),
            duration_seconds=data.get("duration_seconds", 0.0),
            tables_verified=data.get("tables_verified", 0),
            rows_verified=data.get("rows_verified", 0),
            errors=data.get("errors", []),
        )


@dataclass
class IntegrityResult:
    """Result of offsite backup integrity verification."""

    valid: bool
    checksum_match: bool
    size_match: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "checksum_match": self.checksum_match,
            "size_match": self.size_match,
            "errors": self.errors,
        }


# =============================================================================
# Cloud Storage Clients (lazy imports)
# =============================================================================


def _get_s3_client(
    region: str | None = None,
    endpoint_url: str | None = None,
) -> Any:
    """Get an S3 client with lazy import of boto3."""
    import boto3  # type: ignore[import-untyped]

    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def _get_gcs_client() -> Any:
    """Get a GCS client with lazy import of google-cloud-storage."""
    from google.cloud import storage  # type: ignore[import-untyped]

    return storage.Client()


def _get_azure_client(container: str) -> Any:
    """Get an Azure Blob container client with lazy import."""
    import os

    from azure.storage.blob import ContainerClient  # type: ignore[import-untyped]

    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    return ContainerClient.from_connection_string(connection_string, container)


# =============================================================================
# Offsite Backup Manager
# =============================================================================


class OffsiteBackupManager:
    """
    Manages offsite backup automation and restore drill evidence.

    Supports S3, GCS, and Azure Blob Storage providers with:
    - Upload/download with integrity verification
    - Automated restore drill execution and evidence collection
    - Drill history for SOC 2 / compliance auditing
    """

    def __init__(
        self,
        config: OffsiteBackupConfig,
        state_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the offsite backup manager.

        Args:
            config: Offsite backup configuration
            state_dir: Directory to store local state (records, drill history).
                       Defaults to a temp directory if not provided.
        """
        self._config = config

        if state_dir is not None:
            self._state_dir = Path(state_dir)
        else:
            self._state_dir = Path(tempfile.mkdtemp(prefix="offsite_backup_"))
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self._records_path = self._state_dir / "offsite_records.json"
        self._drills_path = self._state_dir / "drill_history.json"

        self._records: dict[str, OffsiteBackupRecord] = {}
        self._drill_history: list[RestoreDrillResult] = []
        self._load_state()

    @property
    def config(self) -> OffsiteBackupConfig:
        """Get the offsite backup configuration."""
        return self._config

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def upload_backup(
        self,
        backup_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> OffsiteBackupRecord:
        """
        Upload a local backup file to offsite cloud storage.

        Args:
            backup_path: Path to the local backup file
            metadata: Additional metadata to store with the record

        Returns:
            OffsiteBackupRecord with upload details

        Raises:
            FileNotFoundError: If backup_path does not exist
            RuntimeError: If upload fails
        """
        source = Path(backup_path)
        if not source.exists():
            raise FileNotFoundError(f"Backup file not found: {source}")

        backup_id = str(uuid4())[:12]
        timestamp = datetime.now(timezone.utc)
        remote_key = (
            f"{self._config.prefix}/{timestamp.strftime('%Y/%m/%d')}/{backup_id}_{source.name}"
        )

        size_bytes = source.stat().st_size
        checksum = self._compute_checksum(source)

        try:
            self._cloud_upload(source, remote_key)
        except Exception as e:
            logger.error("Offsite upload failed for %s: %s", source.name, e)
            raise RuntimeError(f"Offsite upload failed: {e}") from e

        record = OffsiteBackupRecord(
            id=backup_id,
            timestamp=timestamp,
            size_bytes=size_bytes,
            checksum=checksum,
            provider=self._config.provider,
            path=remote_key,
            metadata=metadata or {},
        )

        self._records[backup_id] = record
        self._save_state()

        logger.info(
            "Uploaded offsite backup %s to %s://%s/%s (%.2f MB)",
            backup_id,
            self._config.provider,
            self._config.bucket,
            remote_key,
            size_bytes / 1024 / 1024,
        )

        return record

    def list_offsite_backups(self, limit: int = 50) -> list[OffsiteBackupRecord]:
        """
        List offsite backup records, most recent first.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of OffsiteBackupRecord sorted by timestamp descending
        """
        records = sorted(
            self._records.values(),
            key=lambda r: r.timestamp,
            reverse=True,
        )
        return records[:limit]

    def download_backup(
        self,
        backup_id: str,
        target_path: str | Path,
    ) -> Path:
        """
        Download an offsite backup to a local path.

        Args:
            backup_id: ID of the offsite backup to download
            target_path: Local path to save the downloaded backup

        Returns:
            Path to the downloaded file

        Raises:
            ValueError: If backup_id is not found
            RuntimeError: If download fails
        """
        record = self._records.get(backup_id)
        if record is None:
            raise ValueError(f"Offsite backup not found: {backup_id}")

        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._cloud_download(record.path, target)
        except Exception as e:
            logger.error("Offsite download failed for %s: %s", backup_id, e)
            raise RuntimeError(f"Offsite download failed: {e}") from e

        logger.info("Downloaded offsite backup %s to %s", backup_id, target)
        return target

    def run_restore_drill(self, backup_id: str) -> RestoreDrillResult:
        """
        Run a restore drill: download backup, restore, verify tables/rows.

        This produces auditable evidence that backups can be successfully
        restored, satisfying SOC 2 CC9.1 / CC9.2 requirements.

        Args:
            backup_id: ID of the offsite backup to drill

        Returns:
            RestoreDrillResult with drill evidence
        """
        record = self._records.get(backup_id)
        if record is None:
            return RestoreDrillResult(
                drill_id=str(uuid4())[:12],
                backup_id=backup_id,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                success=False,
                errors=[f"Offsite backup not found: {backup_id}"],
            )

        drill_id = str(uuid4())[:12]
        started_at = datetime.now(timezone.utc)
        start_time = time_module.time()
        errors: list[str] = []
        tables_verified = 0
        rows_verified = 0

        try:
            with tempfile.TemporaryDirectory(prefix="restore_drill_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                downloaded = tmp_path / "drill_backup"

                # Step 1: Download
                self._cloud_download(record.path, downloaded)

                # Step 2: Checksum verification
                local_checksum = self._compute_checksum(downloaded)
                if local_checksum != record.checksum:
                    errors.append(
                        f"Checksum mismatch: expected {record.checksum}, got {local_checksum}"
                    )

                # Step 3: Attempt SQLite restore verification
                db_path = self._prepare_for_verification(downloaded, tmp_path)
                if db_path is not None:
                    tables_verified, rows_verified, db_errors = self._verify_database(db_path)
                    errors.extend(db_errors)

        except Exception as e:
            errors.append(f"Drill failed: {e}")
            logger.error("Restore drill %s failed: %s", drill_id, e)

        duration = time_module.time() - start_time
        completed_at = datetime.now(timezone.utc)
        success = len(errors) == 0

        result = RestoreDrillResult(
            drill_id=drill_id,
            backup_id=backup_id,
            started_at=started_at,
            completed_at=completed_at,
            success=success,
            duration_seconds=round(duration, 3),
            tables_verified=tables_verified,
            rows_verified=rows_verified,
            errors=errors,
        )

        self._drill_history.append(result)
        self._save_state()

        logger.info(
            "Restore drill %s for backup %s: success=%s, tables=%d, rows=%d, duration=%.2fs",
            drill_id,
            backup_id,
            success,
            tables_verified,
            rows_verified,
            duration,
        )

        return result

    def verify_backup_integrity(self, backup_id: str) -> IntegrityResult:
        """
        Verify the integrity of an offsite backup without full restore.

        Downloads the backup and checks checksum and size against the
        stored record.

        Args:
            backup_id: ID of the offsite backup to verify

        Returns:
            IntegrityResult with verification outcome
        """
        record = self._records.get(backup_id)
        if record is None:
            return IntegrityResult(
                valid=False,
                checksum_match=False,
                size_match=False,
                errors=[f"Offsite backup not found: {backup_id}"],
            )

        errors: list[str] = []
        checksum_match = False
        size_match = False

        try:
            with tempfile.TemporaryDirectory(prefix="integrity_check_") as tmp_dir:
                tmp_file = Path(tmp_dir) / "verify"
                self._cloud_download(record.path, tmp_file)

                # Check size
                actual_size = tmp_file.stat().st_size
                size_match = actual_size == record.size_bytes
                if not size_match:
                    errors.append(f"Size mismatch: expected {record.size_bytes}, got {actual_size}")

                # Check checksum
                actual_checksum = self._compute_checksum(tmp_file)
                checksum_match = actual_checksum == record.checksum
                if not checksum_match:
                    errors.append(
                        f"Checksum mismatch: expected {record.checksum}, got {actual_checksum}"
                    )

        except Exception as e:
            errors.append(f"Integrity check failed: {e}")

        valid = checksum_match and size_match and len(errors) == 0

        return IntegrityResult(
            valid=valid,
            checksum_match=checksum_match,
            size_match=size_match,
            errors=errors,
        )

    def get_drill_history(self) -> list[RestoreDrillResult]:
        """
        Get past restore drill results for compliance auditing.

        Returns:
            List of RestoreDrillResult ordered by start time descending
        """
        return sorted(
            self._drill_history,
            key=lambda r: r.started_at,
            reverse=True,
        )

    # -------------------------------------------------------------------------
    # Cloud Operations
    # -------------------------------------------------------------------------

    def _cloud_upload(self, local_path: Path, remote_key: str) -> None:
        """Upload a file to the configured cloud provider."""
        provider = self._config.provider

        if provider == "s3":
            client = _get_s3_client(
                region=self._config.region,
                endpoint_url=self._config.endpoint_url,
            )
            client.upload_file(str(local_path), self._config.bucket, remote_key)

        elif provider == "gcs":
            client = _get_gcs_client()
            bucket = client.bucket(self._config.bucket)
            blob = bucket.blob(remote_key)
            blob.upload_from_filename(str(local_path))

        elif provider == "azure":
            container_client = _get_azure_client(self._config.bucket)
            with open(local_path, "rb") as f:
                container_client.upload_blob(remote_key, f, overwrite=True)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def _cloud_download(self, remote_key: str, local_path: Path) -> None:
        """Download a file from the configured cloud provider."""
        provider = self._config.provider

        if provider == "s3":
            client = _get_s3_client(
                region=self._config.region,
                endpoint_url=self._config.endpoint_url,
            )
            client.download_file(self._config.bucket, remote_key, str(local_path))

        elif provider == "gcs":
            client = _get_gcs_client()
            bucket = client.bucket(self._config.bucket)
            blob = bucket.blob(remote_key)
            blob.download_to_filename(str(local_path))

        elif provider == "azure":
            container_client = _get_azure_client(self._config.bucket)
            with open(local_path, "wb") as f:
                download_stream = container_client.download_blob(remote_key)
                download_stream.readinto(f)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _compute_checksum(self, file_path: Path) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _prepare_for_verification(
        self,
        downloaded: Path,
        tmp_dir: Path,
    ) -> Path | None:
        """
        Prepare a downloaded backup for database verification.

        Handles gzip-compressed and plain SQLite files.

        Returns:
            Path to the SQLite database, or None if not a valid database.
        """
        import gzip

        db_path = tmp_dir / "verify.db"

        # Try gzip decompression first
        try:
            with gzip.open(downloaded, "rb") as f_in:
                with open(db_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            # Validate it's a SQLite file
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT 1")
            conn.close()
            return db_path
        except (gzip.BadGzipFile, OSError, sqlite3.DatabaseError):
            pass

        # Try as plain SQLite
        try:
            shutil.copy(downloaded, db_path)
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT 1")
            conn.close()
            return db_path
        except (OSError, sqlite3.DatabaseError):
            pass

        return None

    def _verify_database(
        self,
        db_path: Path,
    ) -> tuple[int, int, list[str]]:
        """
        Verify a restored SQLite database.

        Returns:
            (tables_verified, rows_verified, errors)
        """
        errors: list[str] = []
        tables_verified = 0
        rows_verified = 0

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Run SQLite integrity check
            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchall()
            if integrity[0][0] != "ok":
                for row in integrity:
                    errors.append(f"Integrity error: {row[0]}")

            # Count tables and rows
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            tables_verified = len(tables)

            for table in tables:
                # table name interpolation, parameterized
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                rows_verified += cursor.fetchone()[0]

            conn.close()

        except (sqlite3.DatabaseError, OSError) as e:
            errors.append(f"Database verification failed: {e}")

        return tables_verified, rows_verified, errors

    # -------------------------------------------------------------------------
    # State Persistence
    # -------------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load records and drill history from disk."""
        if self._records_path.exists():
            try:
                with open(self._records_path) as f:
                    data = json.load(f)
                self._records = {k: OffsiteBackupRecord.from_dict(v) for k, v in data.items()}
            except (OSError, ValueError, KeyError) as e:
                logger.warning("Failed to load offsite records: %s", e)
                self._records = {}

        if self._drills_path.exists():
            try:
                with open(self._drills_path) as f:
                    data = json.load(f)
                self._drill_history = [RestoreDrillResult.from_dict(d) for d in data]
            except (OSError, ValueError, KeyError) as e:
                logger.warning("Failed to load drill history: %s", e)
                self._drill_history = []

    def _save_state(self) -> None:
        """Save records and drill history to disk."""
        try:
            with open(self._records_path, "w") as f:
                json.dump(
                    {k: v.to_dict() for k, v in self._records.items()},
                    f,
                    indent=2,
                )
        except (OSError, ValueError) as e:
            logger.error("Failed to save offsite records: %s", e)

        try:
            with open(self._drills_path, "w") as f:
                json.dump(
                    [d.to_dict() for d in self._drill_history],
                    f,
                    indent=2,
                )
        except (OSError, ValueError) as e:
            logger.error("Failed to save drill history: %s", e)


__all__ = [
    "OffsiteBackupConfig",
    "OffsiteBackupManager",
    "OffsiteBackupRecord",
    "RestoreDrillResult",
    "IntegrityResult",
]
