"""
Database-backed Gauntlet result storage.

Provides persistent storage for Gauntlet validation results with
support for listing, filtering, and comparison operations.

Supports both SQLite (default) and PostgreSQL (via DATABASE_URL env var).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path
from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)
from aragora.storage.connection_factory import is_postgres_backend
from aragora.utils.datetime_helpers import parse_timestamp, utc_now

logger = logging.getLogger(__name__)


@dataclass
class GauntletMetadata:
    """Summary metadata for a stored Gauntlet result."""

    gauntlet_id: str
    input_hash: str
    input_summary: str
    verdict: str
    confidence: float
    robustness_score: float
    critical_count: int
    high_count: int
    total_findings: int
    agents_used: list[str]
    template_used: str | None
    created_at: datetime
    duration_seconds: float


@dataclass
class GauntletInflightRun:
    """In-flight gauntlet run for durability across server restarts."""

    gauntlet_id: str
    status: str  # pending, running, completed, failed
    input_type: str
    input_summary: str
    input_hash: str
    persona: str | None
    profile: str
    agents: list[str]
    created_at: datetime
    updated_at: datetime
    current_phase: str | None = None
    progress_percent: float = 0.0
    error: str | None = None
    org_id: str | None = None
    config_json: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "gauntlet_id": self.gauntlet_id,
            "status": self.status,
            "input_type": self.input_type,
            "input_summary": self.input_summary,
            "input_hash": self.input_hash,
            "persona": self.persona,
            "profile": self.profile,
            "agents": self.agents,
            "created_at": (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else self.created_at
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if isinstance(self.updated_at, datetime)
                else self.updated_at
            ),
            "current_phase": self.current_phase,
            "progress_percent": self.progress_percent,
            "error": self.error,
            "org_id": self.org_id,
        }


class GauntletStorage:
    """
    Persistent storage for Gauntlet validation results.

    Stores complete results with support for:
    - Save/load individual results
    - List results with pagination and filters
    - Compare two results
    - Track result history by input hash

    Supports both SQLite (default) and PostgreSQL backends.

    Usage:
        # SQLite (default)
        storage = GauntletStorage()

        # PostgreSQL (via environment or explicit)
        storage = GauntletStorage(backend="postgresql")

        # Or set DATABASE_URL environment variable
        # export DATABASE_URL=postgresql://user:pass@host:5432/dbname

        storage.save(result)
        result = storage.get("gauntlet-abc123")
        recent = storage.list_recent(limit=20)
    """

    def __init__(
        self,
        db_path: str = "aragora_gauntlet.db",
        backend: str | None = None,
        database_url: str | None = None,
    ):
        """
        Initialize storage with database backend.

        Args:
            db_path: Path to SQLite database file (used when backend="sqlite").
            backend: Database backend type ("sqlite" or "postgresql").
                    If not specified, uses DATABASE_URL env var if set,
                    otherwise defaults to SQLite.
            database_url: PostgreSQL connection URL. Overrides DATABASE_URL env var.
        """
        # Determine backend type
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
        actual_url = database_url or env_url

        if backend is None:
            # Auto-detect based on URL presence
            backend = "postgresql" if actual_url else "sqlite"
        elif is_postgres_backend(backend):
            backend = "postgresql"

        self.backend_type = backend

        # Create appropriate backend
        if backend == "postgresql":
            if not actual_url:
                raise ValueError(
                    "PostgreSQL backend requires DATABASE_URL or database_url parameter"
                )
            if not POSTGRESQL_AVAILABLE:
                raise ImportError(
                    "psycopg2 is required for PostgreSQL support. "
                    "Install with: pip install psycopg2-binary"
                )
            self._backend: DatabaseBackend = PostgreSQLBackend(actual_url)
            logger.info("GauntletStorage using PostgreSQL backend")
        else:
            # SQLite backend
            resolved_path = resolve_db_path(db_path)
            self.db_path = Path(resolved_path)
            self._backend = SQLiteBackend(resolved_path)
            logger.info("GauntletStorage using SQLite backend: %s", resolved_path)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        # Create table - use backend-agnostic SQL
        create_table_sql = """
            CREATE TABLE IF NOT EXISTS gauntlet_results (
                gauntlet_id TEXT PRIMARY KEY,
                input_hash TEXT NOT NULL,
                input_summary TEXT,
                result_json TEXT NOT NULL,
                verdict TEXT NOT NULL,
                confidence REAL,
                robustness_score REAL,
                critical_count INTEGER DEFAULT 0,
                high_count INTEGER DEFAULT 0,
                medium_count INTEGER DEFAULT 0,
                low_count INTEGER DEFAULT 0,
                total_findings INTEGER DEFAULT 0,
                agents_used TEXT,
                template_used TEXT,
                duration_seconds REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                org_id TEXT
            )
        """
        self._backend.execute_write(create_table_sql)

        # Create indexes (syntax works for both SQLite and PostgreSQL)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_gauntlet_input_hash ON gauntlet_results(input_hash)",
            "CREATE INDEX IF NOT EXISTS idx_gauntlet_created ON gauntlet_results(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_gauntlet_verdict ON gauntlet_results(verdict)",
            "CREATE INDEX IF NOT EXISTS idx_gauntlet_org ON gauntlet_results(org_id, created_at DESC)",
        ]
        for idx_sql in indexes:
            try:
                self._backend.execute_write(idx_sql)
            except Exception as e:  # noqa: BLE001 - DB driver exceptions (sqlite3.OperationalError, psycopg2.Error) lack common importable base
                # Index may already exist with different definition
                logger.debug("Index creation skipped: %s", e)

        # Create inflight runs table for durability
        create_inflight_sql = """
            CREATE TABLE IF NOT EXISTS gauntlet_inflight (
                gauntlet_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                input_type TEXT,
                input_summary TEXT,
                input_hash TEXT,
                persona TEXT,
                profile TEXT,
                agents TEXT,
                config_json TEXT,
                current_phase TEXT,
                progress_percent REAL DEFAULT 0,
                error TEXT,
                org_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        self._backend.execute_write(create_inflight_sql)

        # Indexes for inflight table
        inflight_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_inflight_status ON gauntlet_inflight(status)",
            "CREATE INDEX IF NOT EXISTS idx_inflight_org ON gauntlet_inflight(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_inflight_created ON gauntlet_inflight(created_at)",
        ]
        for idx_sql in inflight_indexes:
            try:
                self._backend.execute_write(idx_sql)
            except Exception as e:  # noqa: BLE001 - DB driver exceptions (sqlite3.OperationalError, psycopg2.Error) lack common importable base
                logger.debug("Inflight index creation skipped: %s", e)

    def save(self, result: Any, org_id: str | None = None) -> str:
        """
        Save a GauntletResult to storage.

        Args:
            result: GauntletResult object (from result.py or config.py)
            org_id: Optional organization ID for multi-tenancy

        Returns:
            The gauntlet_id of the saved result
        """
        # Handle both result.py and config.py GauntletResult types
        gauntlet_id = getattr(result, "gauntlet_id", "") or getattr(
            result, "id", f"gauntlet-{id(result)}"
        )
        input_hash = getattr(result, "input_hash", "")
        input_summary = (
            getattr(result, "input_summary", "")[:500] if hasattr(result, "input_summary") else ""
        )
        if not input_hash and input_summary:
            input_hash = hashlib.sha256(input_summary.encode()).hexdigest()

        # Get verdict - handle different result types
        verdict = "unknown"
        if hasattr(result, "verdict"):
            verdict = (
                result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
            )
        elif hasattr(result, "passed"):
            verdict = "pass" if result.passed else "fail"

        confidence = getattr(result, "confidence", 0.5)
        robustness = getattr(result, "robustness_score", 0.5)

        # Count findings by severity
        critical = high = medium = low = 0
        critical_findings = getattr(result, "critical_findings", None)
        high_findings = getattr(result, "high_findings", None)
        medium_findings = getattr(result, "medium_findings", None)
        low_findings = getattr(result, "low_findings", None)

        def _len_if_list(value: Any) -> int:
            if isinstance(value, (list, tuple, set)):
                return len(value)
            return 0

        def _coerce_count(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        if any(
            isinstance(value, (list, tuple, set))
            for value in (critical_findings, high_findings, medium_findings, low_findings)
        ):
            critical = _len_if_list(critical_findings)
            high = _len_if_list(high_findings)
            medium = _len_if_list(medium_findings)
            low = _len_if_list(low_findings)
        elif hasattr(result, "risk_summary"):
            risk_summary = result.risk_summary
            if isinstance(risk_summary, dict):
                critical = risk_summary.get("critical", 0)
                high = risk_summary.get("high", 0)
                medium = risk_summary.get("medium", 0)
                low = risk_summary.get("low", 0)
            else:
                critical = _coerce_count(getattr(risk_summary, "critical", 0))
                high = _coerce_count(getattr(risk_summary, "high", 0))
                medium = _coerce_count(getattr(risk_summary, "medium", 0))
                low = _coerce_count(getattr(risk_summary, "low", 0))
        elif hasattr(result, "severity_counts"):
            counts = result.severity_counts
            if isinstance(counts, dict):
                critical = counts.get("critical", 0)
                high = counts.get("high", 0)
                medium = counts.get("medium", 0)
                low = counts.get("low", 0)

        critical = _coerce_count(critical)
        high = _coerce_count(high)
        medium = _coerce_count(medium)
        low = _coerce_count(low)

        total = getattr(result, "total_findings", None)
        if total is None:
            total = critical + high + medium + low
            vulnerabilities = getattr(result, "vulnerabilities", None)
            if isinstance(vulnerabilities, (list, tuple, set)):
                total = len(vulnerabilities)
            else:
                findings = getattr(result, "findings", None)
                if isinstance(findings, (list, tuple, set)):
                    total = len(findings)
        total = _coerce_count(total)

        agents = getattr(result, "agents_used", None)
        if agents is None:
            agents = getattr(result, "agents_involved", [])
        if not isinstance(agents, list):
            try:
                agents = list(agents)
            except TypeError:
                agents = []
        agents = [str(agent) for agent in agents]
        template = getattr(result, "template_used", None)
        duration = getattr(result, "duration_seconds", 0)

        # Serialize result to JSON
        if hasattr(result, "to_dict"):
            result_dict = result.to_dict()
        else:
            result_dict = {
                "gauntlet_id": gauntlet_id,
                "verdict": verdict,
                "confidence": confidence,
            }

        # Use UPSERT syntax that works for both SQLite and PostgreSQL
        backend_type = getattr(self, "backend_type", None) or getattr(
            self._backend, "backend_type", "sqlite"
        )
        if backend_type == "postgresql":
            sql = """
                INSERT INTO gauntlet_results (
                    gauntlet_id, input_hash, input_summary, result_json,
                    verdict, confidence, robustness_score,
                    critical_count, high_count, medium_count, low_count,
                    total_findings, agents_used, template_used,
                    duration_seconds, org_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (gauntlet_id) DO UPDATE SET
                    input_hash = EXCLUDED.input_hash,
                    input_summary = EXCLUDED.input_summary,
                    result_json = EXCLUDED.result_json,
                    verdict = EXCLUDED.verdict,
                    confidence = EXCLUDED.confidence,
                    robustness_score = EXCLUDED.robustness_score,
                    critical_count = EXCLUDED.critical_count,
                    high_count = EXCLUDED.high_count,
                    medium_count = EXCLUDED.medium_count,
                    low_count = EXCLUDED.low_count,
                    total_findings = EXCLUDED.total_findings,
                    agents_used = EXCLUDED.agents_used,
                    template_used = EXCLUDED.template_used,
                    duration_seconds = EXCLUDED.duration_seconds,
                    org_id = EXCLUDED.org_id
            """
        else:
            sql = """
                INSERT OR REPLACE INTO gauntlet_results (
                    gauntlet_id, input_hash, input_summary, result_json,
                    verdict, confidence, robustness_score,
                    critical_count, high_count, medium_count, low_count,
                    total_findings, agents_used, template_used,
                    duration_seconds, org_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        self._backend.execute_write(
            sql,
            (
                gauntlet_id,
                input_hash,
                input_summary,
                json.dumps(result_dict, default=str),
                verdict,
                confidence,
                robustness,
                critical,
                high,
                medium,
                low,
                total,
                json.dumps(agents),
                template,
                duration,
                org_id,
            ),
        )

        logger.info("Saved gauntlet result: %s", gauntlet_id)
        return gauntlet_id

    def get(self, gauntlet_id: str, org_id: str | None = None) -> dict | None:
        """
        Get a GauntletResult by ID.

        Args:
            gauntlet_id: The gauntlet result ID
            org_id: Optional org ID for ownership verification

        Returns:
            Result dict or None if not found
        """
        if org_id:
            row = self._backend.fetch_one(
                "SELECT result_json FROM gauntlet_results WHERE gauntlet_id = ? AND org_id = ?",
                (gauntlet_id, org_id),
            )
        else:
            row = self._backend.fetch_one(
                "SELECT result_json FROM gauntlet_results WHERE gauntlet_id = ?", (gauntlet_id,)
            )

        return json.loads(row[0]) if row else None

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        org_id: str | None = None,
        verdict: str | None = None,
        min_severity: str | None = None,
    ) -> list[GauntletMetadata]:
        """
        List recent Gauntlet results with optional filters.

        Args:
            limit: Maximum results to return
            offset: Offset for pagination
            org_id: Filter by organization
            verdict: Filter by verdict (pass, fail, conditional)
            min_severity: Only include results with findings at this severity or higher

        Returns:
            List of GauntletMetadata
        """
        query = """
            SELECT gauntlet_id, input_hash, input_summary, verdict, confidence,
                   robustness_score, critical_count, high_count, total_findings,
                   agents_used, template_used, created_at, duration_seconds
            FROM gauntlet_results
            WHERE 1=1
        """
        params: list = []

        if org_id:
            query += " AND org_id = ?"
            params.append(org_id)

        if verdict:
            query += " AND verdict = ?"
            params.append(verdict)

        if min_severity == "critical":
            query += " AND critical_count > 0"
        elif min_severity == "high":
            query += " AND (critical_count > 0 OR high_count > 0)"

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._backend.fetch_all(query, tuple(params))
        results = []
        for row in rows:
            try:
                created_val = row[11]
                if isinstance(created_val, datetime):
                    created = created_val
                elif isinstance(created_val, str):
                    created = datetime.fromisoformat(created_val)
                else:
                    created = datetime.now()
            except (ValueError, TypeError):
                created = datetime.now()

            results.append(
                GauntletMetadata(
                    gauntlet_id=row[0],
                    input_hash=row[1],
                    input_summary=row[2] or "",
                    verdict=row[3],
                    confidence=row[4] or 0,
                    robustness_score=row[5] or 0,
                    critical_count=row[6] or 0,
                    high_count=row[7] or 0,
                    total_findings=row[8] or 0,
                    agents_used=json.loads(row[9]) if row[9] else [],
                    template_used=row[10],
                    created_at=created,
                    duration_seconds=row[12] or 0,
                )
            )

        return results

    def get_history(
        self,
        input_hash: str,
        limit: int = 10,
        org_id: str | None = None,
    ) -> list[GauntletMetadata]:
        """
        Get validation history for a specific input.

        Useful for tracking improvements over time.

        Args:
            input_hash: SHA-256 hash of the input content
            limit: Maximum results to return
            org_id: Filter by organization

        Returns:
            List of GauntletMetadata ordered by date (newest first)
        """
        query = """
            SELECT gauntlet_id, input_hash, input_summary, verdict, confidence,
                   robustness_score, critical_count, high_count, total_findings,
                   agents_used, template_used, created_at, duration_seconds
            FROM gauntlet_results
            WHERE input_hash = ?
        """
        params: list = [input_hash]

        if org_id:
            query += " AND org_id = ?"
            params.append(org_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._backend.fetch_all(query, tuple(params))
        results = []
        for row in rows:
            try:
                created_val = row[11]
                if isinstance(created_val, datetime):
                    created = created_val
                elif isinstance(created_val, str):
                    created = datetime.fromisoformat(created_val)
                else:
                    created = datetime.now()
            except (ValueError, TypeError):
                created = datetime.now()

            results.append(
                GauntletMetadata(
                    gauntlet_id=row[0],
                    input_hash=row[1],
                    input_summary=row[2] or "",
                    verdict=row[3],
                    confidence=row[4] or 0,
                    robustness_score=row[5] or 0,
                    critical_count=row[6] or 0,
                    high_count=row[7] or 0,
                    total_findings=row[8] or 0,
                    agents_used=json.loads(row[9]) if row[9] else [],
                    template_used=row[10],
                    created_at=created,
                    duration_seconds=row[12] or 0,
                )
            )

        return results

    def compare(
        self,
        id1: str,
        id2: str,
        org_id: str | None = None,
    ) -> dict | None:
        """
        Compare two Gauntlet results.

        Args:
            id1: First gauntlet ID (usually newer)
            id2: Second gauntlet ID (usually older)
            org_id: Optional org ID for ownership verification

        Returns:
            Comparison dict with deltas, or None if either result not found
        """
        result1 = self.get(id1, org_id)
        result2 = self.get(id2, org_id)

        if not result1 or not result2:
            return None

        # Extract comparable metrics
        def extract_metrics(r: dict) -> dict:
            risk = r.get("risk_summary", {})
            return {
                "verdict": r.get("verdict", "unknown"),
                "confidence": r.get("confidence", 0),
                "robustness_score": r.get("robustness_score", 0)
                or r.get("attack_summary", {}).get("robustness_score", 0),
                "critical": risk.get("critical", 0),
                "high": risk.get("high", 0),
                "medium": risk.get("medium", 0),
                "low": risk.get("low", 0),
                "total": risk.get("total", 0),
            }

        m1 = extract_metrics(result1)
        m2 = extract_metrics(result2)

        # Calculate deltas (positive = improvement in result1)
        return {
            "result1_id": id1,
            "result2_id": id2,
            "verdict_changed": m1["verdict"] != m2["verdict"],
            "verdict_improved": (m1["verdict"] == "pass" and m2["verdict"] != "pass"),
            "deltas": {
                "confidence": m1["confidence"] - m2["confidence"],
                "robustness": m1["robustness_score"] - m2["robustness_score"],
                "critical": m2["critical"] - m1["critical"],  # Reduction is good
                "high": m2["high"] - m1["high"],
                "medium": m2["medium"] - m1["medium"],
                "low": m2["low"] - m1["low"],
                "total": m2["total"] - m1["total"],
            },
            "metrics_1": m1,
            "metrics_2": m2,
            "improved": (
                m1["critical"] <= m2["critical"]
                and m1["high"] <= m2["high"]
                and m1["robustness_score"] >= m2["robustness_score"]
            ),
        }

    def delete(self, gauntlet_id: str, org_id: str | None = None) -> bool:
        """
        Delete a Gauntlet result.

        Args:
            gauntlet_id: Result ID to delete
            org_id: Optional org ID for ownership verification

        Returns:
            True if deleted, False if not found
        """
        # Check if exists first
        exists = self.get(gauntlet_id, org_id) is not None
        if not exists:
            return False

        if org_id:
            self._backend.execute_write(
                "DELETE FROM gauntlet_results WHERE gauntlet_id = ? AND org_id = ?",
                (gauntlet_id, org_id),
            )
        else:
            self._backend.execute_write(
                "DELETE FROM gauntlet_results WHERE gauntlet_id = ?", (gauntlet_id,)
            )

        logger.info("Deleted gauntlet result: %s", gauntlet_id)
        return True

    def count(self, org_id: str | None = None, verdict: str | None = None) -> int:
        """
        Count total Gauntlet results.

        Args:
            org_id: Filter by organization
            verdict: Filter by verdict

        Returns:
            Total count
        """
        query = "SELECT COUNT(*) FROM gauntlet_results WHERE 1=1"
        params: list = []

        if org_id:
            query += " AND org_id = ?"
            params.append(org_id)

        if verdict:
            query += " AND verdict = ?"
            params.append(verdict)

        row = self._backend.fetch_one(query, tuple(params))
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection/pool."""
        self._backend.close()

    # =========================================================================
    # Inflight Run Management (for durability across server restarts)
    # =========================================================================

    def save_inflight(
        self,
        gauntlet_id: str,
        status: str,
        input_type: str,
        input_summary: str,
        input_hash: str,
        persona: str | None,
        profile: str,
        agents: list[str],
        org_id: str | None = None,
        config_json: str | None = None,
    ) -> str:
        """
        Save or create an inflight gauntlet run.

        Args:
            gauntlet_id: Unique gauntlet ID
            status: Run status (pending, running, completed, failed)
            input_type: Type of input (spec, architecture, etc.)
            input_summary: Summary of input content
            input_hash: SHA-256 hash of input
            persona: Persona used for validation
            profile: Profile used
            agents: List of agents used
            org_id: Organization ID
            config_json: Serialized config (optional)

        Returns:
            The gauntlet_id
        """
        now = datetime.now().isoformat()
        backend_type = getattr(self, "backend_type", None) or "sqlite"

        if backend_type == "postgresql":
            sql = """
                INSERT INTO gauntlet_inflight (
                    gauntlet_id, status, input_type, input_summary, input_hash,
                    persona, profile, agents, config_json, org_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (gauntlet_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
            """
        else:
            sql = """
                INSERT OR REPLACE INTO gauntlet_inflight (
                    gauntlet_id, status, input_type, input_summary, input_hash,
                    persona, profile, agents, config_json, org_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        self._backend.execute_write(
            sql,
            (
                gauntlet_id,
                status,
                input_type,
                input_summary,
                input_hash,
                persona,
                profile,
                json.dumps(agents),
                config_json,
                org_id,
                now,
                now,
            ),
        )

        logger.debug("Saved inflight gauntlet run: %s (status=%s)", gauntlet_id, status)
        return gauntlet_id

    def update_inflight_status(
        self,
        gauntlet_id: str,
        status: str,
        current_phase: str | None = None,
        progress_percent: float | None = None,
        error: str | None = None,
    ) -> bool:
        """
        Update the status of an inflight run.

        Args:
            gauntlet_id: Gauntlet ID to update
            status: New status
            current_phase: Current execution phase
            progress_percent: Progress percentage (0-100)
            error: Error message if failed

        Returns:
            True if updated, False if not found
        """
        now = datetime.now().isoformat()

        # Build dynamic update
        updates = ["status = ?", "updated_at = ?"]
        params: list = [status, now]

        if current_phase is not None:
            updates.append("current_phase = ?")
            params.append(current_phase)

        if progress_percent is not None:
            updates.append("progress_percent = ?")
            params.append(progress_percent)

        if error is not None:
            updates.append("error = ?")
            params.append(error)

        params.append(gauntlet_id)

        sql = f"UPDATE gauntlet_inflight SET {', '.join(updates)} WHERE gauntlet_id = ?"  # noqa: S608 -- dynamic clause from internal state
        self._backend.execute_write(sql, tuple(params))

        logger.debug("Updated inflight gauntlet: %s -> %s", gauntlet_id, status)
        return True

    def get_inflight(self, gauntlet_id: str) -> GauntletInflightRun | None:
        """
        Get an inflight run by ID.

        Args:
            gauntlet_id: Gauntlet ID

        Returns:
            GauntletInflightRun or None
        """
        row = self._backend.fetch_one(
            """
            SELECT gauntlet_id, status, input_type, input_summary, input_hash,
                   persona, profile, agents, current_phase, progress_percent,
                   error, org_id, config_json, created_at, updated_at
            FROM gauntlet_inflight
            WHERE gauntlet_id = ?
            """,
            (gauntlet_id,),
        )

        if not row:
            return None

        return self._row_to_inflight(row)

    def list_inflight(
        self,
        status: str | None = None,
        org_id: str | None = None,
        limit: int = 100,
    ) -> list[GauntletInflightRun]:
        """
        List inflight runs.

        Args:
            status: Filter by status
            org_id: Filter by organization
            limit: Maximum results

        Returns:
            List of GauntletInflightRun
        """
        query = """
            SELECT gauntlet_id, status, input_type, input_summary, input_hash,
                   persona, profile, agents, current_phase, progress_percent,
                   error, org_id, config_json, created_at, updated_at
            FROM gauntlet_inflight
            WHERE 1=1
        """
        params: list = []

        if status:
            query += " AND status = ?"
            params.append(status)

        if org_id:
            query += " AND org_id = ?"
            params.append(org_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._backend.fetch_all(query, tuple(params))
        return [self._row_to_inflight(row) for row in rows]

    def list_stale_inflight(
        self,
        max_age_seconds: int = 7200,
        status: str | None = None,
    ) -> list[GauntletInflightRun]:
        """
        List stale inflight runs (for recovery after restart).

        Args:
            max_age_seconds: Maximum age in seconds (default 2 hours)
            status: Filter by status (default: pending, running)

        Returns:
            List of stale GauntletInflightRun
        """
        query = """
            SELECT gauntlet_id, status, input_type, input_summary, input_hash,
                   persona, profile, agents, current_phase, progress_percent,
                   error, org_id, config_json, created_at, updated_at
            FROM gauntlet_inflight
            WHERE status IN ('pending', 'running')
        """
        params: list = []

        if status:
            query = query.replace("status IN ('pending', 'running')", "status = ?")
            params.append(status)

        query += " ORDER BY created_at ASC"

        rows = self._backend.fetch_all(query, tuple(params))
        results = []

        now = utc_now()
        for row in rows:
            inflight = self._row_to_inflight(row)
            age = (now - inflight.created_at).total_seconds()
            if age > max_age_seconds:
                results.append(inflight)

        return results

    def delete_inflight(self, gauntlet_id: str) -> bool:
        """
        Delete an inflight run (after completion or cleanup).

        Args:
            gauntlet_id: Gauntlet ID to delete

        Returns:
            True if deleted
        """
        self._backend.execute_write(
            "DELETE FROM gauntlet_inflight WHERE gauntlet_id = ?",
            (gauntlet_id,),
        )
        logger.debug("Deleted inflight gauntlet: %s", gauntlet_id)
        return True

    def cleanup_completed_inflight(self, max_age_seconds: int = 3600) -> int:
        """
        Clean up completed/failed inflight runs older than max_age.

        Args:
            max_age_seconds: Maximum age in seconds

        Returns:
            Number of runs cleaned up
        """
        # Get count first
        count_row = self._backend.fetch_one(
            """
            SELECT COUNT(*) FROM gauntlet_inflight
            WHERE status IN ('completed', 'failed')
            """,
        )
        count = count_row[0] if count_row else 0

        if count > 0:
            self._backend.execute_write(
                """
                DELETE FROM gauntlet_inflight
                WHERE status IN ('completed', 'failed')
                """,
            )
            logger.info("Cleaned up %s completed/failed inflight runs", count)

        return count

    def _row_to_inflight(self, row: tuple) -> GauntletInflightRun:
        """Convert a database row to GauntletInflightRun."""
        return GauntletInflightRun(
            gauntlet_id=row[0],
            status=row[1],
            input_type=row[2] or "",
            input_summary=row[3] or "",
            input_hash=row[4] or "",
            persona=row[5],
            profile=row[6] or "default",
            agents=json.loads(row[7]) if row[7] else [],
            current_phase=row[8],
            progress_percent=row[9] or 0.0,
            error=row[10],
            org_id=row[11],
            config_json=row[12],
            created_at=parse_timestamp(row[13], default=utc_now()),
            updated_at=parse_timestamp(row[14], default=utc_now()),
        )


# Module-level singleton for convenience
_default_storage: GauntletStorage | None = None


def get_storage(
    db_path: str = "aragora_gauntlet.db",
    backend: str | None = None,
    database_url: str | None = None,
) -> GauntletStorage:
    """
    Get or create the default GauntletStorage instance.

    Args:
        db_path: Path to SQLite database (used when backend="sqlite")
        backend: Database backend type ("sqlite" or "postgresql")
        database_url: PostgreSQL connection URL

    Returns:
        GauntletStorage instance
    """
    global _default_storage
    if _default_storage is None:
        _default_storage = GauntletStorage(
            db_path=db_path,
            backend=backend,
            database_url=database_url,
        )
    return _default_storage


def reset_storage() -> None:
    """Reset the default storage instance (for testing)."""
    global _default_storage
    if _default_storage is not None:
        _default_storage.close()
        _default_storage = None
