"""
Decision Receipt Storage with Signature Support.

Provides persistent storage for decision receipts with:
- Cryptographic signature storage and verification
- Date range queries
- Retention policy enforcement
- Full-text search on receipt data

Extends the basic receipt storage in audit_trail_store.py with
advanced features for compliance and auditing.

Usage:
    from aragora.storage.receipt_store import get_receipt_store

    store = get_receipt_store()
    await store.save(receipt, signed_receipt=signed_data)
    receipt = await store.get(receipt_id)
    is_valid = await store.verify_signature(receipt_id)
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
import builtins
from typing import Any

from aragora.config import resolve_db_path

from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_RETENTION_DAYS = int(os.environ.get("ARAGORA_RECEIPT_RETENTION_DAYS", "2555"))  # ~7 years


def _compute_receipt_checksum(receipt_data: dict[str, Any]) -> str:
    """Compute the canonical decision-receipt integrity checksum."""
    content = json.dumps(
        {
            "receipt_id": receipt_data.get("receipt_id", ""),
            "verdict": receipt_data.get("verdict", "NEEDS_REVIEW"),
            "confidence": receipt_data.get("confidence", 0.0),
            "findings_count": len(receipt_data.get("findings") or []),
            "critical_count": receipt_data.get("critical_count", 0),
            "timestamp": receipt_data.get("timestamp"),
            "audit_trail_id": receipt_data.get("audit_trail_id"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _linked_worktree_shared_receipt_db_path() -> Path | None:
    """Return a shared repo-root receipt DB path when running in a linked worktree.

    Most databases intentionally isolate linked worktrees under the git common-dir
    data area. Receipts are different: quickstart/API/dashboard should surface the
    same canonical artifacts across developer worktrees, so default them to the
    repo-root data dir unless the caller explicitly overrides ARAGORA_DATA_DIR or
    ARAGORA_RECEIPT_DB_PATH.
    """
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        git_marker = candidate / ".git"
        if not git_marker.is_file():
            if git_marker.is_dir():
                return None
            continue
        try:
            raw = git_marker.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read git metadata from %s: %s", git_marker, exc)
            return None
        prefix = "gitdir:"
        if not raw.startswith(prefix):
            return None
        gitdir = Path(raw[len(prefix) :].strip())
        if not gitdir.is_absolute():
            gitdir = (candidate / gitdir).resolve()
        if gitdir.parent.name != "worktrees":
            return None
        common_git_dir = gitdir.parent.parent
        repo_root = common_git_dir.parent
        shared_data_dir = repo_root / ".nomic"
        if not shared_data_dir.exists() and (repo_root / "data").exists():
            shared_data_dir = repo_root / "data"
        return shared_data_dir / "receipts.db"
    return None


def _default_receipt_db_path() -> Path:
    """Resolve the canonical default receipt DB path."""
    explicit_path = os.environ.get("ARAGORA_RECEIPT_DB_PATH")
    if explicit_path:
        return Path(explicit_path)
    if not (os.environ.get("ARAGORA_DATA_DIR") or os.environ.get("ARAGORA_NOMIC_DIR")):
        shared_worktree_path = _linked_worktree_shared_receipt_db_path()
        if shared_worktree_path is not None:
            return shared_worktree_path
    return Path(resolve_db_path("receipts.db"))


DEFAULT_DB_PATH = _default_receipt_db_path()

# Global singleton
_receipt_store: ReceiptStore | None = None
_store_lock = threading.RLock()


def _receipt_json_default(value: Any) -> Any:
    """Serialize non-JSON-native types in receipt payloads."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return list(value)
    return str(value)


def _clamp_confidence(value: Any, *, default: float = 0.0) -> float:
    """Clamp receipt confidence-like values into the canonical 0.0-1.0 range."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


def _normalize_receipt_payload(
    payload: dict[str, Any],
    *,
    default_confidence: float = 0.0,
) -> dict[str, Any]:
    """Normalize receipt confidence fields without mutating caller-owned data."""
    normalized = dict(payload)
    consensus = normalized.get("consensus_proof")
    fallback_confidence = (
        consensus.get("confidence") if isinstance(consensus, dict) else default_confidence
    )
    normalized_confidence = _clamp_confidence(
        normalized.get("confidence"),
        default=_clamp_confidence(fallback_confidence, default=default_confidence),
    )
    if "confidence" in normalized or isinstance(consensus, dict):
        normalized["confidence"] = normalized_confidence
    if isinstance(consensus, dict):
        normalized_consensus = dict(consensus)
        normalized_consensus["confidence"] = _clamp_confidence(
            normalized_consensus.get("confidence"),
            default=normalized_confidence,
        )
        normalized["consensus_proof"] = normalized_consensus
    return normalized


@dataclass
class StoredReceipt:
    """A stored decision receipt with signature metadata."""

    receipt_id: str
    gauntlet_id: str
    debate_id: str | None
    created_at: float
    expires_at: float | None
    verdict: str
    confidence: float
    risk_level: str
    risk_score: float
    checksum: str
    # Signature fields
    signature: str | None = None
    signature_algorithm: str | None = None
    signature_key_id: str | None = None
    signed_at: float | None = None
    # RFC 3161 trusted timestamp
    timestamp_token: str | None = None  # Base64-encoded TSA response
    timestamp_tsa_url: str | None = None
    timestamp_at: float | None = None
    # Legal hold (prevents deletion even after retention expires)
    legal_hold: bool = False
    legal_hold_reason: str | None = None
    legal_hold_placed_by: str | None = None
    legal_hold_placed_at: float | None = None
    legal_hold_matter_id: str | None = None
    # Links
    audit_trail_id: str | None = None
    # Full data
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize stale confidence values when receipts are materialized."""
        self.confidence = _clamp_confidence(self.confidence)
        self.data = _normalize_receipt_payload(self.data or {}, default_confidence=self.confidence)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        result: dict[str, Any] = {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "debate_id": self.debate_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "checksum": self.checksum,
            "audit_trail_id": self.audit_trail_id,
            "is_signed": self.signature is not None,
            "has_timestamp": self.timestamp_token is not None,
            "legal_hold": self.legal_hold,
        }
        if self.signature:
            result["signature_metadata"] = {
                "algorithm": self.signature_algorithm,
                "key_id": self.signature_key_id,
                "signed_at": self.signed_at,
            }
        if self.timestamp_token:
            result["timestamp_metadata"] = {
                "tsa_url": self.timestamp_tsa_url,
                "timestamp_at": self.timestamp_at,
            }
        if self.legal_hold:
            result["legal_hold_metadata"] = {
                "reason": self.legal_hold_reason,
                "placed_by": self.legal_hold_placed_by,
                "placed_at": self.legal_hold_placed_at,
                "matter_id": self.legal_hold_matter_id,
            }
        return result

    def to_full_dict(self) -> dict[str, Any]:
        """Convert to full dictionary including data payload.

        The data blob (from data_json) provides the base, then the
        authoritative structured DB column values from to_dict() are
        layered on top so they always win if the blob is stale.
        """
        result = _normalize_receipt_payload(self.data, default_confidence=self.confidence)
        result.update(self.to_dict())
        return result


@dataclass
class SignatureVerificationResult:
    """Result of signature verification."""

    receipt_id: str
    is_valid: bool
    algorithm: str | None = None
    key_id: str | None = None
    signed_at: float | None = None
    verified_at: float = field(default_factory=lambda: time.time())
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to API response."""
        return {
            "receipt_id": self.receipt_id,
            "signature_valid": self.is_valid,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signed_at": self.signed_at,
            "verification_timestamp": datetime.fromtimestamp(
                self.verified_at, tz=timezone.utc
            ).isoformat(),
            "error": self.error,
        }


class ReceiptStore:
    """
    Database-backed storage for decision receipts with signature support.

    Supports SQLite (default) and PostgreSQL backends.
    Provides full CRUD operations, signature verification, and retention management.
    """

    # SQLite schema (uses REAL for floating point)
    SCHEMA_STATEMENTS_SQLITE = [
        """
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY,
            gauntlet_id TEXT NOT NULL UNIQUE,
            debate_id TEXT,
            created_at REAL NOT NULL,
            expires_at REAL,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL,
            risk_level TEXT NOT NULL,
            risk_score REAL NOT NULL DEFAULT 0.0,
            checksum TEXT NOT NULL,
            signature TEXT,
            signature_algorithm TEXT,
            signature_key_id TEXT,
            signed_at REAL,
            timestamp_token TEXT,
            timestamp_tsa_url TEXT,
            timestamp_at REAL,
            legal_hold INTEGER DEFAULT 0,
            legal_hold_reason TEXT,
            legal_hold_placed_by TEXT,
            legal_hold_placed_at REAL,
            legal_hold_matter_id TEXT,
            audit_trail_id TEXT,
            data_json TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_receipts_created ON receipts(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_expires ON receipts(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_gauntlet ON receipts(gauntlet_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_debate ON receipts(debate_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_verdict ON receipts(verdict)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_risk ON receipts(risk_level)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_signed ON receipts(signed_at)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_legal_hold ON receipts(legal_hold)",
    ]

    # Migration statements for existing databases (add new columns if missing)
    MIGRATION_STATEMENTS_SQLITE = [
        "ALTER TABLE receipts ADD COLUMN timestamp_token TEXT",
        "ALTER TABLE receipts ADD COLUMN timestamp_tsa_url TEXT",
        "ALTER TABLE receipts ADD COLUMN timestamp_at REAL",
        "ALTER TABLE receipts ADD COLUMN legal_hold INTEGER DEFAULT 0",
        "ALTER TABLE receipts ADD COLUMN legal_hold_reason TEXT",
        "ALTER TABLE receipts ADD COLUMN legal_hold_placed_by TEXT",
        "ALTER TABLE receipts ADD COLUMN legal_hold_placed_at REAL",
        "ALTER TABLE receipts ADD COLUMN legal_hold_matter_id TEXT",
    ]

    # PostgreSQL schema (uses DOUBLE PRECISION for floating point, JSONB for data)
    SCHEMA_STATEMENTS_POSTGRESQL = [
        """
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY,
            gauntlet_id TEXT NOT NULL UNIQUE,
            debate_id TEXT,
            created_at DOUBLE PRECISION NOT NULL,
            expires_at DOUBLE PRECISION,
            verdict TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            risk_level TEXT NOT NULL,
            risk_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            checksum TEXT NOT NULL,
            signature TEXT,
            signature_algorithm TEXT,
            signature_key_id TEXT,
            signed_at DOUBLE PRECISION,
            timestamp_token TEXT,
            timestamp_tsa_url TEXT,
            timestamp_at DOUBLE PRECISION,
            legal_hold BOOLEAN DEFAULT FALSE,
            legal_hold_reason TEXT,
            legal_hold_placed_by TEXT,
            legal_hold_placed_at DOUBLE PRECISION,
            legal_hold_matter_id TEXT,
            audit_trail_id TEXT,
            data_json JSONB NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_receipts_created ON receipts(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_expires ON receipts(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_gauntlet ON receipts(gauntlet_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_debate ON receipts(debate_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_verdict ON receipts(verdict)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_risk ON receipts(risk_level)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_signed ON receipts(signed_at)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_legal_hold ON receipts(legal_hold)",
        # PostgreSQL-specific: GIN index for JSONB queries
        "CREATE INDEX IF NOT EXISTS idx_receipts_data_gin ON receipts USING GIN (data_json)",
    ]

    # Migration statements for existing PostgreSQL databases
    MIGRATION_STATEMENTS_POSTGRESQL = [
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS timestamp_token TEXT",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS timestamp_tsa_url TEXT",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS timestamp_at DOUBLE PRECISION",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS legal_hold BOOLEAN DEFAULT FALSE",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS legal_hold_reason TEXT",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS legal_hold_placed_by TEXT",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS legal_hold_placed_at DOUBLE PRECISION",
        "ALTER TABLE receipts ADD COLUMN IF NOT EXISTS legal_hold_matter_id TEXT",
    ]

    # Legacy property for backwards compatibility
    SCHEMA_STATEMENTS = SCHEMA_STATEMENTS_SQLITE

    def __init__(
        self,
        db_path: Path | None = None,
        backend: str | None = None,
        database_url: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        file_receipt_dirs: builtins.list[Path] | None = None,
    ):
        """
        Initialize receipt store.

        Args:
            db_path: Path to SQLite database (used when backend="sqlite")
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
            retention_days: Days to retain receipts (default: 2555 = ~7 years)
            file_receipt_dirs: Explicit directories to scan for JSON receipt files.
                If None (default), auto-detects CWD/.aragora/receipts/ and
                ~/.aragora/receipts/.  Pass an empty list to disable file scanning.
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.retention_days = retention_days
        self._file_receipt_dirs_override = file_receipt_dirs

        # Determine backend type
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
        actual_url = database_url or env_url

        if backend is None:
            env_backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite").lower()
            backend = "postgresql" if (actual_url and env_backend == "postgresql") else "sqlite"

        self.backend_type = backend
        self._backend: DatabaseBackend | None = None

        if backend == "postgresql":
            if not actual_url:
                raise ValueError("PostgreSQL backend requires DATABASE_URL")
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("psycopg2 required for PostgreSQL")
            self._backend = PostgreSQLBackend(actual_url)
            logger.info("ReceiptStore using PostgreSQL backend")
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._backend = SQLiteBackend(str(self.db_path))
            logger.info("ReceiptStore using SQLite backend: %s", self.db_path)

        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema based on backend type."""
        import sqlite3

        if self._backend is None:
            return

        # Select appropriate schema and migration statements for backend
        if self.backend_type == "postgresql":
            schema_statements = self.SCHEMA_STATEMENTS_POSTGRESQL
            migration_statements = self.MIGRATION_STATEMENTS_POSTGRESQL
        else:
            schema_statements = self.SCHEMA_STATEMENTS_SQLITE
            migration_statements = self.MIGRATION_STATEMENTS_SQLITE

        # Bootstrap fresh databases before ALTERs; upgrade old tables before indexes.
        # A failed table creation is fatal, not a skippable additive migration.
        self._backend.execute_write(schema_statements[0])

        for statement in migration_statements:
            try:
                self._backend.execute_write(statement)
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as e:
                logger.debug("Migration statement skipped: %s", e)

        for statement in schema_statements[1:]:
            try:
                self._backend.execute_write(statement)
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as e:
                logger.debug("Schema statement skipped: %s", e)

    def close(self) -> None:
        """Close any open backend resources."""
        backend = self._backend
        self._backend = None
        if backend is None:
            return
        try:
            backend.close()
        except builtins.Exception as exc:
            logger.debug("ReceiptStore backend close failed: %s", exc)

    # =========================================================================
    # File-based receipt fallback (.aragora/receipts/*.json)
    # =========================================================================

    def _file_receipt_dirs(self) -> builtins.list[Path]:
        """Return candidate directories where quickstart/CLI write JSON receipts.

        If ``file_receipt_dirs`` was provided at construction time, returns
        that list directly.  Otherwise auto-detects:
        1. CWD/.aragora/receipts/
        2. ~/.aragora/receipts/
        """
        if self._file_receipt_dirs_override is not None:
            return [d for d in self._file_receipt_dirs_override if d.is_dir()]
        candidates: builtins.list[Path] = []
        cwd_dir = Path.cwd() / ".aragora" / "receipts"
        if cwd_dir.is_dir():
            candidates.append(cwd_dir)
        home_dir = Path.home() / ".aragora" / "receipts"
        if home_dir.is_dir() and home_dir != cwd_dir:
            candidates.append(home_dir)
        return candidates

    @staticmethod
    def _parse_file_receipt(data: dict[str, Any], source_path: Path) -> StoredReceipt:
        """Convert a JSON receipt dict (as written by quickstart) to a StoredReceipt."""
        normalized_data = _normalize_receipt_payload(data)

        # Receipt ID: prefer receipt_id, then nested receipt.id, then filename stem
        receipt_nested = normalized_data.get("receipt", {}) or {}
        receipt_id = (
            normalized_data.get("receipt_id") or receipt_nested.get("id") or source_path.stem
        )
        gauntlet_id = normalized_data.get("gauntlet_id") or receipt_id

        # Timestamp
        created_at: float
        raw_ts = normalized_data.get("timestamp")
        if isinstance(raw_ts, str):
            try:
                created_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                created_at = source_path.stat().st_mtime
        elif isinstance(raw_ts, (int, float)):
            created_at = float(raw_ts)
        else:
            created_at = source_path.stat().st_mtime

        # Verdict normalization
        verdict = str(normalized_data.get("verdict") or "UNKNOWN").upper()

        # Confidence
        confidence = _clamp_confidence(normalized_data.get("confidence"), default=0.0)

        # Risk
        risk_level = str(normalized_data.get("risk_level") or "MEDIUM").upper()
        try:
            risk_score = float(normalized_data.get("risk_score") or 0.0)
        except (TypeError, ValueError):
            risk_score = 0.0

        checksum = str(
            normalized_data.get("checksum")
            or normalized_data.get("artifact_hash")
            or receipt_nested.get("artifact_hash")
            or ""
        )

        return StoredReceipt(
            receipt_id=receipt_id,
            gauntlet_id=gauntlet_id,
            debate_id=normalized_data.get("debate_id"),
            created_at=created_at,
            expires_at=None,
            verdict=verdict,
            confidence=confidence,
            risk_level=risk_level,
            risk_score=risk_score,
            checksum=checksum,
            signature=normalized_data.get("signature"),
            signature_algorithm=normalized_data.get("signature_algorithm"),
            signature_key_id=normalized_data.get("signature_key_id"),
            signed_at=None,
            audit_trail_id=normalized_data.get("audit_trail_id"),
            data=normalized_data,
        )

    def _load_file_receipts(self) -> builtins.list[StoredReceipt]:
        """Scan .aragora/receipts/ directories and return StoredReceipt objects."""
        results: builtins.list[StoredReceipt] = []
        seen_ids: set[str] = set()
        for receipts_dir in self._file_receipt_dirs():
            for json_file in sorted(receipts_dir.glob("*.json"), reverse=True):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    sr = self._parse_file_receipt(data, json_file)
                    if sr.receipt_id not in seen_ids:
                        seen_ids.add(sr.receipt_id)
                        results.append(sr)
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    logger.debug("Skipping malformed receipt file %s: %s", json_file, exc)
        return results

    def _get_file_receipt(self, receipt_id: str) -> StoredReceipt | None:
        """Look up a single receipt by ID from the file-based store."""
        for sr in self._load_file_receipts():
            if sr.receipt_id == receipt_id:
                return sr
        return None

    def _get_file_receipt_by_gauntlet(self, gauntlet_id: str) -> StoredReceipt | None:
        """Look up a single receipt by gauntlet_id from the file-based store."""
        for sr in self._load_file_receipts():
            if sr.gauntlet_id == gauntlet_id:
                return sr
        return None

    # =========================================================================
    # Core CRUD Operations
    # =========================================================================

    def save(
        self,
        receipt_dict: dict[str, Any],
        signed_receipt: dict[str, Any] | None = None,
    ) -> str:
        """
        Save a decision receipt.

        Args:
            receipt_dict: Receipt data from DecisionReceipt.to_dict()
            signed_receipt: Optional SignedReceipt data with signature

        Returns:
            receipt_id of saved receipt
        """
        if self._backend is None:
            raise RuntimeError("ReceiptStore not initialized")

        normalized_receipt = _normalize_receipt_payload(receipt_dict)

        receipt_id = normalized_receipt.get("receipt_id", "")
        gauntlet_id = normalized_receipt.get("gauntlet_id", "")
        debate_id = normalized_receipt.get("debate_id")

        # Parse timestamp
        created_at = normalized_receipt.get("timestamp", time.time())
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                created_at = time.time()

        # Calculate expiration
        expires_at = created_at + (self.retention_days * 86400)

        # Extract signature data if provided
        signature = None
        signature_algorithm = None
        signature_key_id = None
        signed_at = None

        if signed_receipt:
            signature = signed_receipt.get("signature")
            sig_meta = signed_receipt.get("signature_metadata", {})
            signature_algorithm = sig_meta.get("algorithm")
            signature_key_id = sig_meta.get("key_id")
            signed_at_str = sig_meta.get("timestamp")
            if signed_at_str:
                try:
                    signed_at = datetime.fromisoformat(
                        signed_at_str.replace("Z", "+00:00")
                    ).timestamp()
                except (ValueError, AttributeError):
                    signed_at = time.time()

        params = (
            receipt_id,
            gauntlet_id,
            debate_id,
            created_at,
            expires_at,
            normalized_receipt.get("verdict", ""),
            normalized_receipt.get("confidence", 0.0),
            normalized_receipt.get("risk_level", "MEDIUM"),
            normalized_receipt.get("risk_score", 0.0),
            normalized_receipt.get("checksum", ""),
            signature,
            signature_algorithm,
            signature_key_id,
            signed_at,
            normalized_receipt.get("audit_trail_id"),
            json.dumps(normalized_receipt, default=_receipt_json_default),
        )

        # Use backend-specific upsert syntax
        if self.backend_type == "postgresql":
            self._backend.execute_write(
                """
                INSERT INTO receipts
                (receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                 verdict, confidence, risk_level, risk_score, checksum,
                 signature, signature_algorithm, signature_key_id, signed_at,
                 audit_trail_id, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (receipt_id) DO UPDATE SET
                    gauntlet_id = EXCLUDED.gauntlet_id,
                    debate_id = EXCLUDED.debate_id,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at,
                    verdict = EXCLUDED.verdict,
                    confidence = EXCLUDED.confidence,
                    risk_level = EXCLUDED.risk_level,
                    risk_score = EXCLUDED.risk_score,
                    checksum = EXCLUDED.checksum,
                    signature = EXCLUDED.signature,
                    signature_algorithm = EXCLUDED.signature_algorithm,
                    signature_key_id = EXCLUDED.signature_key_id,
                    signed_at = EXCLUDED.signed_at,
                    audit_trail_id = EXCLUDED.audit_trail_id,
                    data_json = EXCLUDED.data_json
                """,
                params,
            )
        else:
            # SQLite uses INSERT OR REPLACE
            self._backend.execute_write(
                """
                INSERT OR REPLACE INTO receipts
                (receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                 verdict, confidence, risk_level, risk_score, checksum,
                 signature, signature_algorithm, signature_key_id, signed_at,
                 audit_trail_id, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        logger.debug("Saved receipt: %s", receipt_id)
        return receipt_id

    def get(self, receipt_id: str) -> StoredReceipt | None:
        """
        Get a receipt by ID.

        Falls back to scanning .aragora/receipts/ JSON files when the
        receipt is not found in the database.

        Args:
            receipt_id: Receipt ID to retrieve

        Returns:
            StoredReceipt or None if not found
        """
        if self._backend is not None:
            row = self._backend.fetch_one(
                """
                SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                       verdict, confidence, risk_level, risk_score, checksum,
                       signature, signature_algorithm, signature_key_id, signed_at,
                       audit_trail_id, data_json
                FROM receipts WHERE receipt_id = ?
                """,
                (receipt_id,),
            )
            if row:
                return self._row_to_stored_receipt(row)

        # Fallback: file-based receipts
        return self._get_file_receipt(receipt_id)

    def get_by_gauntlet(self, gauntlet_id: str) -> StoredReceipt | None:
        """Get receipt by gauntlet ID.

        Falls back to scanning .aragora/receipts/ JSON files.
        """
        if self._backend is not None:
            row = self._backend.fetch_one(
                """
                SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                       verdict, confidence, risk_level, risk_score, checksum,
                       signature, signature_algorithm, signature_key_id, signed_at,
                       audit_trail_id, data_json
                FROM receipts WHERE gauntlet_id = ?
                """,
                (gauntlet_id,),
            )
            if row:
                return self._row_to_stored_receipt(row)

        # Fallback: file-based receipts
        return self._get_file_receipt_by_gauntlet(gauntlet_id)

    def _row_to_stored_receipt(self, row: tuple) -> StoredReceipt:
        """Convert database row to StoredReceipt."""
        return StoredReceipt(
            receipt_id=row[0],
            gauntlet_id=row[1],
            debate_id=row[2],
            created_at=row[3],
            expires_at=row[4],
            verdict=row[5],
            confidence=row[6],
            risk_level=row[7],
            risk_score=row[8],
            checksum=row[9],
            signature=row[10],
            signature_algorithm=row[11],
            signature_key_id=row[12],
            signed_at=row[13],
            audit_trail_id=row[14],
            data=self._deserialize_receipt_data(row[15]),
        )

    @staticmethod
    def _deserialize_receipt_data(raw_data: Any) -> dict[str, Any]:
        """Return a normalized receipt payload or fail closed on corruption."""
        if raw_data in (None, ""):
            return {}
        data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        if not isinstance(data, dict):
            raise ValueError("Receipt data_json must deserialize to an object.")
        return data

    @staticmethod
    def _filter_file_receipt(
        sr: StoredReceipt,
        *,
        verdict: str | None = None,
        risk_level: str | None = None,
        debate_id: str | None = None,
        date_from: float | None = None,
        date_to: float | None = None,
        signed_only: bool = False,
    ) -> bool:
        """Return True if a file-based StoredReceipt passes the given filters."""
        if verdict and sr.verdict != verdict:
            return False
        if risk_level and sr.risk_level != risk_level:
            return False
        if debate_id and sr.debate_id != debate_id:
            return False
        if date_from and sr.created_at < date_from:
            return False
        if date_to and sr.created_at > date_to:
            return False
        if signed_only and sr.signature is None:
            return False
        return True

    def _merge_file_receipts(
        self,
        db_results: builtins.list[StoredReceipt],
        *,
        verdict: str | None = None,
        risk_level: str | None = None,
        debate_id: str | None = None,
        date_from: float | None = None,
        date_to: float | None = None,
        signed_only: bool = False,
        sort_by: str = "created_at",
        order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> builtins.list[StoredReceipt]:
        """Merge file-based receipts with DB results, de-duplicate, filter, sort, paginate."""
        db_ids = {r.receipt_id for r in db_results}
        file_receipts = [
            sr
            for sr in self._load_file_receipts()
            if sr.receipt_id not in db_ids
            and self._filter_file_receipt(
                sr,
                verdict=verdict,
                risk_level=risk_level,
                debate_id=debate_id,
                date_from=date_from,
                date_to=date_to,
                signed_only=signed_only,
            )
        ]
        if not file_receipts:
            return db_results

        merged = db_results + file_receipts
        sort_key = (
            sort_by
            if sort_by in {"created_at", "confidence", "risk_score", "signed_at"}
            else "created_at"
        )
        merged.sort(
            key=lambda r: getattr(r, sort_key, 0) or 0,
            reverse=(order.lower() == "desc"),
        )
        return merged[offset : offset + limit] if offset else merged[:limit]

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        verdict: str | None = None,
        risk_level: str | None = None,
        date_from: float | None = None,
        date_to: float | None = None,
        signed_only: bool = False,
        sort_by: str = "created_at",
        order: str = "desc",
        debate_id: str | None = None,
    ) -> builtins.list[StoredReceipt]:
        """
        List receipts with filtering and pagination.

        Merges results from the database with any JSON receipt files
        found in .aragora/receipts/ directories (written by quickstart/CLI).

        Args:
            limit: Maximum receipts to return
            offset: Pagination offset
            verdict: Filter by verdict (APPROVED, REJECTED, etc.)
            risk_level: Filter by risk level (LOW, MEDIUM, HIGH, CRITICAL)
            date_from: Filter by created_at >= date_from (timestamp)
            date_to: Filter by created_at <= date_to (timestamp)
            signed_only: Only return signed receipts
            sort_by: Field to sort by (created_at, confidence, risk_score)
            order: Sort order (asc, desc)

        Returns:
            List of StoredReceipt objects
        """
        db_results: builtins.list[StoredReceipt] = []
        if self._backend is not None:
            conditions = []
            params: list[Any] = []

            if verdict:
                conditions.append("verdict = ?")
                params.append(verdict)
            if risk_level:
                conditions.append("risk_level = ?")
                params.append(risk_level)
            if debate_id:
                conditions.append("debate_id = ?")
                params.append(debate_id)
            if date_from:
                conditions.append("created_at >= ?")
                params.append(date_from)
            if date_to:
                conditions.append("created_at <= ?")
                params.append(date_to)
            if signed_only:
                conditions.append("signature IS NOT NULL")

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # Validate sort field
            valid_sort_fields = {"created_at", "confidence", "risk_score", "signed_at"}
            if sort_by not in valid_sort_fields:
                sort_by = "created_at"
            order_clause = "DESC" if order.lower() == "desc" else "ASC"

            params.extend([limit, offset])

            rows = self._backend.fetch_all(
                f"""
                SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                       verdict, confidence, risk_level, risk_score, checksum,
                       signature, signature_algorithm, signature_key_id, signed_at,
                       audit_trail_id, data_json
                FROM receipts
                WHERE {where_clause}
                ORDER BY {sort_by} {order_clause}
                LIMIT ? OFFSET ?
                """,  # nosec B608 - where_clause built from hardcoded conditions  # noqa: S608
                tuple(params),
            )

            db_results = [self._row_to_stored_receipt(row) for row in rows]

        return self._merge_file_receipts(
            db_results,
            verdict=verdict,
            risk_level=risk_level,
            debate_id=debate_id,
            date_from=date_from,
            date_to=date_to,
            signed_only=signed_only,
            sort_by=sort_by,
            order=order,
            limit=limit,
            offset=offset,
        )

    def count(
        self,
        verdict: str | None = None,
        risk_level: str | None = None,
        date_from: float | None = None,
        date_to: float | None = None,
        signed_only: bool = False,
        debate_id: str | None = None,
    ) -> int:
        """Get total count of receipts matching filters.

        Includes file-based receipts from .aragora/receipts/ that are not
        already present in the database.
        """
        db_count = 0
        db_ids: set[str] = set()

        if self._backend is not None:
            conditions = []
            params: list[Any] = []

            if verdict:
                conditions.append("verdict = ?")
                params.append(verdict)
            if risk_level:
                conditions.append("risk_level = ?")
                params.append(risk_level)
            if debate_id:
                conditions.append("debate_id = ?")
                params.append(debate_id)
            if date_from:
                conditions.append("created_at >= ?")
                params.append(date_from)
            if date_to:
                conditions.append("created_at <= ?")
                params.append(date_to)
            if signed_only:
                conditions.append("signature IS NOT NULL")

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            row = self._backend.fetch_one(
                f"SELECT COUNT(*) FROM receipts WHERE {where_clause}",  # nosec B608  # noqa: S608
                tuple(params),
            )
            db_count = row[0] if row else 0

            # Collect DB receipt IDs to de-duplicate against file receipts
            id_rows = self._backend.fetch_all(
                f"SELECT receipt_id FROM receipts WHERE {where_clause}",  # nosec B608  # noqa: S608
                tuple(params),
            )
            db_ids = {r[0] for r in id_rows}

        # Count file-based receipts not already in DB
        file_extra = sum(
            1
            for sr in self._load_file_receipts()
            if sr.receipt_id not in db_ids
            and self._filter_file_receipt(
                sr,
                verdict=verdict,
                risk_level=risk_level,
                debate_id=debate_id,
                date_from=date_from,
                date_to=date_to,
                signed_only=signed_only,
            )
        )

        return db_count + file_extra

    # =========================================================================
    # Full-Text Search
    # =========================================================================

    def search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        verdict: str | None = None,
        risk_level: str | None = None,
    ) -> builtins.list[StoredReceipt]:
        """
        Full-text search across receipt content.

        Searches verdict reasoning, task descriptions, and findings.
        Uses PostgreSQL TSVECTOR for PostgreSQL backend, LIKE for SQLite.

        Args:
            query: Search query (minimum 3 characters)
            limit: Maximum results to return (max 100)
            offset: Pagination offset
            verdict: Optional filter by verdict
            risk_level: Optional filter by risk level

        Returns:
            List of StoredReceipt objects matching the query
        """
        if self._backend is None:
            return []

        if not query or len(query) < 3:
            return []

        # Sanitize and limit
        limit = min(limit, 100)
        params: list[Any] = []
        conditions = []

        if self.backend_type == "postgresql":
            # PostgreSQL: Use TSVECTOR for efficient full-text search on JSONB
            search_condition = """
                (to_tsvector('english', COALESCE(data_json->>'verdict_reasoning', '')) ||
                 to_tsvector('english', COALESCE(data_json->>'task', '')) ||
                 to_tsvector('english', COALESCE(data_json->>'description', '')) ||
                 to_tsvector('english', COALESCE(data_json::text, '')))
                @@ plainto_tsquery('english', ?)
            """
            conditions.append(search_condition)
            params.append(query)
        else:
            # SQLite: Use LIKE for text search (case-insensitive)
            search_pattern = f"%{query}%"
            search_condition = """
                (data_json LIKE ? OR verdict LIKE ?)
            """
            conditions.append(search_condition)
            params.extend([search_pattern, search_pattern])

        # Apply optional filters
        if verdict:
            conditions.append("verdict = ?")
            params.append(verdict)
        if risk_level:
            conditions.append("risk_level = ?")
            params.append(risk_level)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        rows = self._backend.fetch_all(
            f"""
            SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                   verdict, confidence, risk_level, risk_score, checksum,
                   signature, signature_algorithm, signature_key_id, signed_at,
                   audit_trail_id, data_json
            FROM receipts
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,  # nosec B608 - where_clause built from hardcoded conditions  # noqa: S608
            tuple(params),
        )

        return [self._row_to_stored_receipt(row) for row in rows]

    def search_count(
        self,
        query: str,
        verdict: str | None = None,
        risk_level: str | None = None,
    ) -> int:
        """
        Get total count of receipts matching search query.

        Args:
            query: Search query (minimum 3 characters)
            verdict: Optional filter by verdict
            risk_level: Optional filter by risk level

        Returns:
            Total count of matching receipts
        """
        if self._backend is None:
            return 0

        if not query or len(query) < 3:
            return 0

        params: list[Any] = []
        conditions = []

        if self.backend_type == "postgresql":
            search_condition = """
                (to_tsvector('english', COALESCE(data_json->>'verdict_reasoning', '')) ||
                 to_tsvector('english', COALESCE(data_json->>'task', '')) ||
                 to_tsvector('english', COALESCE(data_json->>'description', '')) ||
                 to_tsvector('english', COALESCE(data_json::text, '')))
                @@ plainto_tsquery('english', ?)
            """
            conditions.append(search_condition)
            params.append(query)
        else:
            search_pattern = f"%{query}%"
            search_condition = """
                (data_json LIKE ? OR verdict LIKE ?)
            """
            conditions.append(search_condition)
            params.extend([search_pattern, search_pattern])

        if verdict:
            conditions.append("verdict = ?")
            params.append(verdict)
        if risk_level:
            conditions.append("risk_level = ?")
            params.append(risk_level)

        where_clause = " AND ".join(conditions)

        row = self._backend.fetch_one(
            f"SELECT COUNT(*) FROM receipts WHERE {where_clause}",  # nosec B608  # noqa: S608
            tuple(params),
        )
        return row[0] if row else 0

    # =========================================================================
    # Signature Operations
    # =========================================================================

    def update_signature(
        self,
        receipt_id: str,
        signature: str,
        algorithm: str,
        key_id: str,
    ) -> bool:
        """
        Update receipt with signature.

        Args:
            receipt_id: Receipt to sign
            signature: Base64-encoded signature
            algorithm: Signing algorithm (HMAC-SHA256, RSA-SHA256, Ed25519)
            key_id: Identifier of signing key

        Returns:
            True if updated, False if receipt not found
        """
        if self._backend is None:
            return False

        # Check receipt exists
        existing = self.get(receipt_id)
        if not existing:
            return False

        signed_at = time.time()

        self._backend.execute_write(
            """
            UPDATE receipts
            SET signature = ?, signature_algorithm = ?,
                signature_key_id = ?, signed_at = ?
            WHERE receipt_id = ?
            """,
            (signature, algorithm, key_id, signed_at, receipt_id),
        )
        logger.info("Updated signature for receipt: %s", receipt_id)
        return True

    def verify_signature(self, receipt_id: str) -> SignatureVerificationResult:
        """
        Verify the cryptographic signature of a receipt.

        Args:
            receipt_id: Receipt ID to verify

        Returns:
            SignatureVerificationResult with validation status
        """
        receipt = self.get(receipt_id)

        if not receipt:
            return SignatureVerificationResult(
                receipt_id=receipt_id,
                is_valid=False,
                error="Receipt not found",
            )

        if not receipt.signature:
            return SignatureVerificationResult(
                receipt_id=receipt_id,
                is_valid=False,
                error="Receipt is not signed",
            )

        try:
            from aragora.storage.receipt_signing import (
                ReceiptSigner,
                SignatureMetadata,
                SignedReceipt,
            )

            # Reconstruct signature metadata
            sig_meta = SignatureMetadata(
                algorithm=receipt.signature_algorithm or "HMAC-SHA256",
                key_id=receipt.signature_key_id or "unknown",
                timestamp=(
                    datetime.fromtimestamp(receipt.signed_at or 0, tz=timezone.utc).isoformat()
                    if receipt.signed_at
                    else datetime.now(timezone.utc).isoformat()
                ),
            )

            # Reconstruct signed receipt
            signed = SignedReceipt(
                receipt_data=receipt.data,
                signature=receipt.signature,
                signature_metadata=sig_meta,
            )

            # Verify using signer
            signer = ReceiptSigner()
            is_valid = signer.verify(signed)

            return SignatureVerificationResult(
                receipt_id=receipt_id,
                is_valid=is_valid,
                algorithm=receipt.signature_algorithm,
                key_id=receipt.signature_key_id,
                signed_at=receipt.signed_at,
            )

        except ImportError as e:
            logger.warning("Signing module not available: %s", e)
            return SignatureVerificationResult(
                receipt_id=receipt_id,
                is_valid=False,
                error="Signing module not available",
            )
        except (ValueError, RuntimeError, KeyError, TypeError) as e:
            logger.warning("Signature verification failed: %s", e)
            return SignatureVerificationResult(
                receipt_id=receipt_id,
                is_valid=False,
                algorithm=receipt.signature_algorithm,
                key_id=receipt.signature_key_id,
                signed_at=receipt.signed_at,
                error="Signature verification failed",
            )

    def verify_batch(
        self, receipt_ids: builtins.list[str]
    ) -> tuple[builtins.list[SignatureVerificationResult], dict[str, int]]:
        """
        Verify signatures for multiple receipts.

        Args:
            receipt_ids: List of receipt IDs to verify

        Returns:
            Tuple of (results list, summary dict)
        """
        results = []
        summary = {"total": len(receipt_ids), "valid": 0, "invalid": 0, "not_signed": 0}

        for receipt_id in receipt_ids:
            result = self.verify_signature(receipt_id)
            results.append(result)

            if result.is_valid:
                summary["valid"] += 1
            elif result.error == "Receipt is not signed":
                summary["not_signed"] += 1
            else:
                summary["invalid"] += 1

        return results, summary

    # =========================================================================
    # Integrity Verification
    # =========================================================================

    def verify_integrity(self, receipt_id: str) -> dict[str, Any]:
        """
        Verify the integrity checksum of a receipt.

        Args:
            receipt_id: Receipt ID to verify

        Returns:
            Dict with checksum verification result
        """
        receipt = self.get(receipt_id)

        if not receipt:
            return {
                "receipt_id": receipt_id,
                "integrity_valid": False,
                "error": "Receipt not found",
            }

        try:
            computed_checksum = _compute_receipt_checksum(receipt.data)

            is_valid = computed_checksum == receipt.checksum

            return {
                "receipt_id": receipt_id,
                "integrity_valid": is_valid,
                "stored_checksum": receipt.checksum,
                "computed_checksum": computed_checksum,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

        except (ValueError, KeyError, TypeError, ImportError):
            return {
                "receipt_id": receipt_id,
                "integrity_valid": False,
                "error": "Integrity verification failed",
            }

    # =========================================================================
    # Retention & Cleanup
    # =========================================================================

    def cleanup_expired(
        self,
        retention_days: int | None = None,
        operator: str = "system:retention_cleanup",
        log_deletions: bool = True,
    ) -> int:
        """
        Remove receipts older than retention period with audit trail.

        Logs all deletions to the receipt deletion log before removing
        for GDPR/SOC2 compliance.

        Args:
            retention_days: Override default retention (default: use store's setting)
            operator: Identifier for who/what initiated the cleanup
            log_deletions: Whether to log deletions to audit trail (default True)

        Returns:
            Number of receipts removed
        """
        if self._backend is None:
            return 0

        days = retention_days if retention_days is not None else self.retention_days
        cutoff = time.time() - (days * 86400)

        # Get receipts to be deleted (for audit logging)
        rows = self._backend.fetch_all(
            """
            SELECT receipt_id, checksum, gauntlet_id, verdict
            FROM receipts WHERE created_at < ?
            """,
            (cutoff,),
        )

        if not rows:
            return 0

        count = len(rows)

        # Log deletions before removing
        if log_deletions:
            try:
                from aragora.storage.receipt_deletion_log import get_receipt_deletion_log

                deletion_log = get_receipt_deletion_log()
                receipts_to_log = [
                    {
                        "receipt_id": row[0],
                        "checksum": row[1],
                        "gauntlet_id": row[2],
                        "verdict": row[3],
                        "metadata": {"retention_days": days},
                    }
                    for row in rows
                ]
                deletion_log.log_batch_deletion(
                    receipts=receipts_to_log,
                    reason="retention_expired",
                    operator=operator,
                )
                logger.info("Logged %s receipt deletions to audit trail", count)
            except (OSError, RuntimeError, ValueError, ImportError) as e:
                logger.warning("Failed to log deletions to audit trail: %s", e)
                # Continue with deletion even if logging fails
                # (configurable behavior could be added)

        # Now delete the receipts
        self._backend.execute_write(
            "DELETE FROM receipts WHERE created_at < ?",
            (cutoff,),
        )
        logger.info("Removed %s expired receipts (older than %s days)", count, days)

        return count

    def get_stats(self) -> dict[str, Any]:
        """Get receipt statistics."""
        if self._backend is None:
            return {}

        total = self.count()
        signed = self.count(signed_only=True)

        # Verdict breakdown
        verdict_counts = {}
        for verdict in ["APPROVED", "REJECTED", "NEEDS_REVIEW", "INCONCLUSIVE"]:
            verdict_counts[verdict.lower()] = self.count(verdict=verdict)

        # Risk level breakdown
        risk_counts = {}
        for risk in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            risk_counts[risk.lower()] = self.count(risk_level=risk)

        return {
            "total": total,
            "signed": signed,
            "unsigned": total - signed,
            "by_verdict": verdict_counts,
            "by_risk_level": risk_counts,
            "retention_days": self.retention_days,
        }

    def get_by_user(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        include_data: bool = True,
    ) -> tuple[builtins.list[StoredReceipt], int]:
        """
        Get all receipts associated with a user (GDPR DSAR support).

        Searches for receipts where the user_id appears in the data JSON.

        Args:
            user_id: User identifier to search for
            limit: Max results to return
            offset: Pagination offset
            include_data: Include full data payload

        Returns:
            Tuple of (list of receipts, total count)
        """
        if self._backend is None:
            return [], 0

        user_pattern = f'%"{user_id}"%'
        query = """
            SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                   verdict, confidence, risk_level, risk_score, checksum,
                   signature, signature_algorithm, signature_key_id, signed_at,
                   audit_trail_id, data_json
            FROM receipts
            WHERE json_extract(data_json, '$.user_id') = ?
               OR json_extract(data_json, '$.requestor_id') = ?
               OR json_extract(data_json, '$.created_by') = ?
               OR data_json LIKE ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        count_query = """
            SELECT COUNT(*)
            FROM receipts
            WHERE json_extract(data_json, '$.user_id') = ?
               OR json_extract(data_json, '$.requestor_id') = ?
               OR json_extract(data_json, '$.created_by') = ?
               OR data_json LIKE ?
        """
        params = (user_id, user_id, user_id, user_pattern, limit, offset)
        count_params = (user_id, user_id, user_id, user_pattern)

        rows = self._backend.fetch_all(query, params)
        receipts = [self._row_to_stored_receipt(row) for row in rows]

        count_row = self._backend.fetch_one(count_query, count_params)
        total = count_row[0] if count_row else 0

        return receipts, total

    def get_retention_status(self) -> dict[str, Any]:
        """
        Get retention status for GDPR compliance reporting.

        Returns:
            Dictionary with retention status information
        """
        if self._backend is None:
            return {}

        now = time.time()

        # Get oldest and newest timestamps
        timestamp_row = self._backend.fetch_one(
            "SELECT MIN(created_at), MAX(created_at) FROM receipts"
        )
        oldest_at = timestamp_row[0] if timestamp_row and timestamp_row[0] else None
        newest_at = timestamp_row[1] if timestamp_row and timestamp_row[1] else None

        # Get already expired count
        expired_row = self._backend.fetch_one(
            "SELECT COUNT(*) FROM receipts WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        already_expired = expired_row[0] if expired_row else 0

        return {
            "retention_policy": {
                "retention_days": self.retention_days,
                "retention_years": round(self.retention_days / 365, 1),
            },
            "age_distribution": {
                "0-30_days": 0,
                "31-90_days": 0,
                "91-365_days": 0,
                "1-3_years": 0,
                "3-7_years": 0,
                "over_7_years": 0,
            },
            "expiring_receipts": {
                "next_30_days": 0,
                "next_90_days": 0,
                "next_365_days": 0,
            },
            "already_expired": already_expired,
            "timestamps": {
                "oldest_receipt": (
                    datetime.fromtimestamp(oldest_at, tz=timezone.utc).isoformat()
                    if oldest_at
                    else None
                ),
                "newest_receipt": (
                    datetime.fromtimestamp(newest_at, tz=timezone.utc).isoformat()
                    if newest_at
                    else None
                ),
            },
            "total_receipts": self.count(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================================
    # Legal Hold Management
    # =========================================================================

    def place_legal_hold(
        self,
        receipt_id: str,
        reason: str,
        placed_by: str,
        matter_id: str | None = None,
    ) -> bool:
        """
        Place a legal hold on a receipt to prevent deletion.

        When a receipt is under legal hold, it cannot be deleted even after
        the retention period expires. Used for litigation holds and regulatory
        investigations.

        Args:
            receipt_id: The receipt to place under hold
            reason: Reason for the hold (e.g., "Litigation - Smith v. Corp")
            placed_by: User or system placing the hold
            matter_id: Optional legal matter reference

        Returns:
            True if the hold was placed successfully
        """
        if self._backend is None:
            return False

        query = """
            UPDATE receipts
            SET legal_hold = ?,
                legal_hold_reason = ?,
                legal_hold_placed_by = ?,
                legal_hold_placed_at = ?,
                legal_hold_matter_id = ?
            WHERE receipt_id = ?
        """
        now = time.time()
        params = (True, reason, placed_by, now, matter_id, receipt_id)

        try:
            self._backend.execute_write(query, params)
            logger.info("Legal hold placed on receipt %s by %s: %s", receipt_id, placed_by, reason)
            return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to place legal hold on receipt %s: %s", receipt_id, e)
            return False

    def remove_legal_hold(self, receipt_id: str, removed_by: str) -> bool:
        """
        Remove a legal hold from a receipt.

        Args:
            receipt_id: The receipt to release
            removed_by: User removing the hold (for audit)

        Returns:
            True if the hold was removed successfully
        """
        if self._backend is None:
            return False

        query = """
            UPDATE receipts
            SET legal_hold = ?,
                legal_hold_reason = NULL,
                legal_hold_placed_by = NULL,
                legal_hold_placed_at = NULL,
                legal_hold_matter_id = NULL
            WHERE receipt_id = ?
        """
        params = (False, receipt_id)

        try:
            self._backend.execute_write(query, params)
            logger.info("Legal hold removed from receipt %s by %s", receipt_id, removed_by)
            return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to remove legal hold from receipt %s: %s", receipt_id, e)
            return False

    def list_under_legal_hold(
        self,
        matter_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> builtins.list[StoredReceipt]:
        """
        List all receipts currently under legal hold.

        Args:
            matter_id: Optional filter by legal matter ID
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of receipts under legal hold
        """
        if self._backend is None:
            return []

        params: tuple[Any, ...]
        if matter_id:
            query = """
                SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                       verdict, confidence, risk_level, risk_score, checksum,
                       signature, signature_algorithm, signature_key_id, signed_at,
                       timestamp_token, timestamp_tsa_url, timestamp_at,
                       legal_hold, legal_hold_reason, legal_hold_placed_by,
                       legal_hold_placed_at, legal_hold_matter_id,
                       audit_trail_id, data_json
                FROM receipts
                WHERE legal_hold = ? AND legal_hold_matter_id = ?
                ORDER BY legal_hold_placed_at DESC
                LIMIT ? OFFSET ?
            """
            params = (True, matter_id, limit, offset)
        else:
            query = """
                SELECT receipt_id, gauntlet_id, debate_id, created_at, expires_at,
                       verdict, confidence, risk_level, risk_score, checksum,
                       signature, signature_algorithm, signature_key_id, signed_at,
                       timestamp_token, timestamp_tsa_url, timestamp_at,
                       legal_hold, legal_hold_reason, legal_hold_placed_by,
                       legal_hold_placed_at, legal_hold_matter_id,
                       audit_trail_id, data_json
                FROM receipts
                WHERE legal_hold = ?
                ORDER BY legal_hold_placed_at DESC
                LIMIT ? OFFSET ?
            """
            params = (True, limit, offset)

        rows = self._backend.fetch_all(query, params)
        return [self._row_to_stored_receipt_extended(row) for row in rows]

    def is_under_legal_hold(self, receipt_id: str) -> bool:
        """
        Check if a receipt is under legal hold.

        Args:
            receipt_id: The receipt to check

        Returns:
            True if the receipt is under legal hold
        """
        if self._backend is None:
            return False

        row = self._backend.fetch_one(
            "SELECT legal_hold FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        )
        return bool(row and row[0])

    # =========================================================================
    # Trusted Timestamp Management
    # =========================================================================

    def add_timestamp(
        self,
        receipt_id: str,
        timestamp_token: str,
        tsa_url: str,
    ) -> bool:
        """
        Add an RFC 3161 trusted timestamp to a receipt.

        Args:
            receipt_id: The receipt to timestamp
            timestamp_token: Base64-encoded TSA response
            tsa_url: The TSA server URL used

        Returns:
            True if the timestamp was added successfully
        """
        if self._backend is None:
            return False

        query = """
            UPDATE receipts
            SET timestamp_token = ?,
                timestamp_tsa_url = ?,
                timestamp_at = ?
            WHERE receipt_id = ?
        """
        now = time.time()
        params = (timestamp_token, tsa_url, now, receipt_id)

        try:
            self._backend.execute_write(query, params)
            logger.info("Timestamp added to receipt %s from %s", receipt_id, tsa_url)
            return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to add timestamp to receipt %s: %s", receipt_id, e)
            return False

    def _row_to_stored_receipt_extended(self, row: tuple) -> StoredReceipt:
        """Convert a database row to StoredReceipt including new fields."""
        return StoredReceipt(
            receipt_id=row[0],
            gauntlet_id=row[1],
            debate_id=row[2],
            created_at=row[3],
            expires_at=row[4],
            verdict=row[5],
            confidence=row[6],
            risk_level=row[7],
            risk_score=row[8],
            checksum=row[9],
            signature=row[10],
            signature_algorithm=row[11],
            signature_key_id=row[12],
            signed_at=row[13],
            timestamp_token=row[14],
            timestamp_tsa_url=row[15],
            timestamp_at=row[16],
            legal_hold=bool(row[17]),
            legal_hold_reason=row[18],
            legal_hold_placed_by=row[19],
            legal_hold_placed_at=row[20],
            legal_hold_matter_id=row[21],
            audit_trail_id=row[22],
            data=self._deserialize_receipt_data(row[23]),
        )


# =========================================================================
# Module-level Functions
# =========================================================================


def get_receipt_store() -> ReceiptStore:
    """
    Get or create the global receipt store.

    Returns:
        ReceiptStore singleton instance
    """
    global _receipt_store

    with _store_lock:
        if _receipt_store is None:
            _receipt_store = ReceiptStore()
        return _receipt_store


def set_receipt_store(store: ReceiptStore | None) -> None:
    """
    Set the global receipt store (for testing).

    Args:
        store: ReceiptStore instance or None to reset
    """
    global _receipt_store

    with _store_lock:
        previous = _receipt_store
        _receipt_store = store

    if previous is not None and previous is not store:
        try:
            previous.close()
        except builtins.Exception as exc:
            logger.debug("Failed to close previous receipt store: %s", exc)


def close_receipt_store() -> None:
    """Close and clear the global receipt store singleton."""
    global _receipt_store

    with _store_lock:
        store = _receipt_store
        _receipt_store = None

    if store is not None:
        try:
            store.close()
        except builtins.Exception as exc:
            logger.debug("Failed to close receipt store during shutdown: %s", exc)


atexit.register(close_receipt_store)
