"""SQLite-backed persistent store for DecisionPlans.

Provides CRUD operations for DecisionPlan persistence with filtering
by debate_id and approval status. Replaces the in-memory store in
executor.py for production use.

Usage:
    store = PlanStore()
    store.create(plan)
    plan = store.get(plan_id)
    plans = store.list(status=PlanStatus.AWAITING_APPROVAL, limit=20)
    store.update_status(plan_id, PlanStatus.APPROVED, approved_by="user-123")
"""

from __future__ import annotations

import builtins
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
import uuid

from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    ApprovalRecord,
    BudgetAllocation,
    DecisionPlan,
    ImplementationProfile,
    PlanStatus,
)
from aragora.pipeline.risk_register import RiskLevel, RiskRegister
from aragora.pipeline.verification_plan import VerificationPlan
from aragora.implement.types import ImplementPlan

logger = logging.getLogger(__name__)

# Default database location
_DEFAULT_DB_DIR = os.environ.get("ARAGORA_DATA_DIR", str(Path.home() / ".aragora"))
_DEFAULT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "plans.db")


def _get_db_path() -> str:
    """Resolve the plan store database path."""
    try:
        from aragora.persistence.db_config import get_default_data_dir

        return str(get_default_data_dir() / "plans.db")
    except ImportError:
        return _DEFAULT_DB_PATH


class PlanStore:
    """SQLite-backed store for DecisionPlan objects.

    Thread-safe via SQLite WAL mode. Each method creates its own
    connection to support concurrent access from handler threads.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()
        self._ensure_dir()
        self._ensure_table()

    def _ensure_dir(self) -> None:
        """Create parent directory if needed."""
        parent = Path(self._db_path).parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection with WAL mode."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create the plans table if it does not exist."""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    debate_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'created',
                    approval_mode TEXT NOT NULL DEFAULT 'risk_based',
                    max_auto_risk TEXT NOT NULL DEFAULT 'low',
                    approved_by TEXT,
                    rejection_reason TEXT,
                    budget_json TEXT,
                    approval_record_json TEXT,
                    implementation_profile_json TEXT,
                    risk_register_json TEXT,
                    verification_plan_json TEXT,
                    implement_plan_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plans_debate_id
                ON plans(debate_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plans_status
                ON plans(status)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plan_executions (
                    execution_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    debate_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_json TEXT,
                    metadata_json TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plan_executions_plan_id
                ON plan_executions(plan_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plan_executions_debate_id
                ON plan_executions(debate_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plan_executions_status
                ON plan_executions(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plan_executions_started_at
                ON plan_executions(started_at DESC)
            """)

            # Backward-compatible schema migration for existing databases.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(plans)").fetchall()}
            if "max_auto_risk" not in columns:
                conn.execute(
                    "ALTER TABLE plans ADD COLUMN max_auto_risk TEXT NOT NULL DEFAULT 'low'"
                )
            if "implementation_profile_json" not in columns:
                conn.execute("ALTER TABLE plans ADD COLUMN implementation_profile_json TEXT")
            if "risk_register_json" not in columns:
                conn.execute("ALTER TABLE plans ADD COLUMN risk_register_json TEXT")
            if "verification_plan_json" not in columns:
                conn.execute("ALTER TABLE plans ADD COLUMN verification_plan_json TEXT")
            if "implement_plan_json" not in columns:
                conn.execute("ALTER TABLE plans ADD COLUMN implement_plan_json TEXT")
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    def create(self, plan: DecisionPlan) -> None:
        """Insert a new plan into the store."""
        try:
            from aragora.pipeline.receipt_gate import ensure_plan_receipt

            ensure_plan_receipt(plan)
        except Exception as exc:  # noqa: BLE001 - keep persistence available; execution gate enforces
            logger.warning("Failed to pre-persist decision receipt for plan %s: %s", plan.id, exc)

        now = datetime.now(timezone.utc).isoformat()
        budget_json = json.dumps(plan.budget.to_dict()) if plan.budget else "{}"
        approval_json = json.dumps(plan.approval_record.to_dict()) if plan.approval_record else None
        implementation_profile_json = (
            json.dumps(plan.implementation_profile.to_dict())
            if plan.implementation_profile
            else None
        )
        risk_register_json = (
            json.dumps(plan.risk_register.to_dict()) if plan.risk_register else None
        )
        verification_plan_json = (
            json.dumps(plan.verification_plan.to_dict()) if plan.verification_plan else None
        )
        implement_plan_json = (
            json.dumps(plan.implement_plan.to_dict()) if plan.implement_plan else None
        )
        metadata_json = json.dumps(plan.metadata) if plan.metadata else "{}"

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO plans (
                    id, debate_id, task, status, approval_mode,
                    max_auto_risk,
                    approved_by, rejection_reason, budget_json,
                    approval_record_json, implementation_profile_json,
                    risk_register_json, verification_plan_json, implement_plan_json,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.debate_id,
                    plan.task,
                    plan.status.value,
                    plan.approval_mode.value,
                    plan.max_auto_risk.value,
                    plan.approval_record.approver_id if plan.approval_record else None,
                    plan.approval_record.reason
                    if plan.approval_record and not plan.approval_record.approved
                    else None,
                    budget_json,
                    approval_json,
                    implementation_profile_json,
                    risk_register_json,
                    verification_plan_json,
                    implement_plan_json,
                    metadata_json,
                    plan.created_at.isoformat(),
                    now,
                ),
            )
            conn.commit()
            logger.info("Stored plan %s for debate %s", plan.id, plan.debate_id)
        finally:
            conn.close()

    def get(self, plan_id: str) -> DecisionPlan | None:
        """Retrieve a plan by ID."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_plan(row)
        finally:
            conn.close()

    def list(
        self,
        *,
        debate_id: str | None = None,
        status: PlanStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DecisionPlan]:
        """List plans with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []

        if debate_id is not None:
            clauses.append("debate_id = ?")
            params.append(debate_id)
        if status is not None:
            status_val = status.value if isinstance(status, PlanStatus) else status
            clauses.append("status = ?")
            params.append(status_val)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        query = f"SELECT * FROM plans {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"  # noqa: S608 -- internal query construction
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_plan(row) for row in rows]
        finally:
            conn.close()

    def count(
        self,
        *,
        debate_id: str | None = None,
        status: PlanStatus | str | None = None,
    ) -> int:
        """Count plans matching the given filters."""
        clauses: list[str] = []
        params: list[Any] = []

        if debate_id is not None:
            clauses.append("debate_id = ?")
            params.append(debate_id)
        if status is not None:
            status_val = status.value if isinstance(status, PlanStatus) else status
            clauses.append("status = ?")
            params.append(status_val)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        conn = self._connect()
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM plans {where}", params).fetchone()  # noqa: S608 -- internal query construction
            return row[0] if row else 0
        finally:
            conn.close()

    def update_status(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        """Update a plan's status. Returns True if the plan was found and updated."""
        now = datetime.now(timezone.utc).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, now]

        if approved_by is not None:
            fields.append("approved_by = ?")
            params.append(approved_by)

        if rejection_reason is not None:
            fields.append("rejection_reason = ?")
            params.append(rejection_reason)

        if status == PlanStatus.APPROVED:
            fields.append("approved_at = ?")
            params.append(now)
            # Store approval record
            approval_record = ApprovalRecord(
                approved=True,
                approver_id=approved_by or "unknown",
                reason="",
            )
            fields.append("approval_record_json = ?")
            params.append(json.dumps(approval_record.to_dict()))

        if status == PlanStatus.REJECTED:
            approval_record = ApprovalRecord(
                approved=False,
                approver_id=approved_by or "unknown",
                reason=rejection_reason or "",
            )
            fields.append("approval_record_json = ?")
            params.append(json.dumps(approval_record.to_dict()))

        params.append(plan_id)

        conn = self._connect()
        try:
            cursor = conn.execute(
                f"UPDATE plans SET {', '.join(fields)} WHERE id = ?",  # noqa: S608 -- column list from internal state
                params,
            )
            conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info("Updated plan %s to status %s", plan_id, status.value)
                if status in (PlanStatus.APPROVED, PlanStatus.REJECTED, PlanStatus.COMPLETED):
                    try:
                        from aragora.pipeline.receipt_gate import sync_plan_receipt_state

                        plan = self.get(plan_id)
                        if plan is not None:
                            sync_plan_receipt_state(plan, on_status=status)
                    except Exception as exc:  # noqa: BLE001 - do not mask status update
                        logger.warning(
                            "Failed to synchronize decision receipt for plan %s: %s",
                            plan_id,
                            exc,
                        )
            return updated
        finally:
            conn.close()

    def update_status_if_current(
        self,
        plan_id: str,
        *,
        expected_statuses: Sequence[PlanStatus],
        new_status: PlanStatus,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        """Atomically update status only when the current status matches.

        Returns True if the row was claimed/updated, False otherwise.
        """
        expected_values = [status.value for status in expected_statuses]
        if not expected_values:
            return False

        now = datetime.now(timezone.utc).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [new_status.value, now]

        if approved_by is not None:
            fields.append("approved_by = ?")
            params.append(approved_by)

        if rejection_reason is not None:
            fields.append("rejection_reason = ?")
            params.append(rejection_reason)

        if new_status == PlanStatus.APPROVED:
            fields.append("approved_at = ?")
            params.append(now)
            approval_record = ApprovalRecord(
                approved=True,
                approver_id=approved_by or "unknown",
                reason="",
            )
            fields.append("approval_record_json = ?")
            params.append(json.dumps(approval_record.to_dict()))

        if new_status == PlanStatus.REJECTED:
            approval_record = ApprovalRecord(
                approved=False,
                approver_id=approved_by or "unknown",
                reason=rejection_reason or "",
            )
            fields.append("approval_record_json = ?")
            params.append(json.dumps(approval_record.to_dict()))

        placeholders = ", ".join("?" for _ in expected_values)
        query = f"UPDATE plans SET {', '.join(fields)} WHERE id = ? AND status IN ({placeholders})"  # noqa: S608 -- parameterized query
        query_params = [*params, plan_id, *expected_values]

        conn = self._connect()
        try:
            cursor = conn.execute(query, query_params)
            conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info(
                    "Atomically updated plan %s to status %s (expected: %s)",
                    plan_id,
                    new_status.value,
                    ",".join(expected_values),
                )
                if new_status in (PlanStatus.APPROVED, PlanStatus.REJECTED, PlanStatus.COMPLETED):
                    try:
                        from aragora.pipeline.receipt_gate import sync_plan_receipt_state

                        plan = self.get(plan_id)
                        if plan is not None:
                            sync_plan_receipt_state(plan, on_status=new_status)
                    except Exception as exc:  # noqa: BLE001 - do not mask status update
                        logger.warning(
                            "Failed to synchronize decision receipt for plan %s: %s",
                            plan_id,
                            exc,
                        )
            return updated
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Execution records
    # -------------------------------------------------------------------------

    def create_execution_record(
        self,
        *,
        plan_id: str,
        debate_id: str,
        status: str,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> str:
        """Create a persistent execution record and return the execution ID."""
        record_id = execution_id or f"exec-{uuid.uuid4().hex[:12]}"
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO plan_executions (
                    execution_id, plan_id, debate_id, correlation_id, status,
                    error_json, metadata_json, started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    plan_id,
                    debate_id,
                    corr_id,
                    status,
                    json.dumps(error) if error else None,
                    json.dumps(metadata) if metadata else "{}",
                    now,
                    now if status in {"succeeded", "failed", "canceled"} else None,
                    now,
                ),
            )
            conn.commit()
            return record_id
        finally:
            conn.close()

    def update_execution_record(
        self,
        execution_id: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> bool:
        """Update an execution record. Returns True when record exists."""
        now = datetime.now(timezone.utc).isoformat()
        fields = ["updated_at = ?"]
        params: list[Any] = [now]

        if status is not None:
            fields.append("status = ?")
            params.append(status)
            if status in {"succeeded", "failed", "canceled"}:
                fields.append("completed_at = ?")
                params.append(now)

        if metadata is not None:
            fields.append("metadata_json = ?")
            params.append(json.dumps(metadata))

        if error is not None:
            fields.append("error_json = ?")
            params.append(json.dumps(error))

        params.append(execution_id)

        conn = self._connect()
        try:
            cursor = conn.execute(
                f"UPDATE plan_executions SET {', '.join(fields)} WHERE execution_id = ?",  # noqa: S608 -- column list from internal state
                params,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_execution_record(self, execution_id: str) -> dict[str, Any] | None:
        """Fetch a single execution record by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM plan_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_execution_record(row)
        finally:
            conn.close()

    def list_execution_records(
        self,
        *,
        plan_id: str | None = None,
        debate_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[dict[str, Any]]:
        """List execution records filtered by plan/debate/status."""
        clauses: list[str] = []
        params: list[Any] = []

        if plan_id is not None:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if debate_id is not None:
            clauses.append("debate_id = ?")
            params.append(debate_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        query = f"SELECT * FROM plan_executions {where} ORDER BY started_at DESC LIMIT ? OFFSET ?"  # noqa: S608 -- internal query construction
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_execution_record(row) for row in rows]
        finally:
            conn.close()

    def get_recent_outcomes(self, limit: int = 10) -> builtins.list[dict[str, Any]]:
        """Get recent plan outcomes for feedback into planning.

        Returns plans that have reached a terminal status (completed,
        failed, rejected) along with their execution records, ordered
        by most recent first.

        Args:
            limit: Maximum number of outcomes to return

        Returns:
            List of outcome dicts with keys: plan_id, task, status,
            debate_id, created_at, execution_status, execution_error
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT p.id, p.task, p.status, p.debate_id, p.created_at,
                       e.status AS exec_status,
                       e.error_json AS exec_error
                FROM plans p
                LEFT JOIN plan_executions e ON e.plan_id = p.id
                WHERE p.status IN ('completed', 'failed', 'rejected', 'executing')
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            outcomes: list[dict[str, Any]] = []
            for row in rows:
                exec_error = None
                if row["exec_error"]:
                    try:
                        exec_error = json.loads(row["exec_error"])
                    except (TypeError, ValueError, json.JSONDecodeError):
                        exec_error = {"message": str(row["exec_error"])}

                outcomes.append(
                    {
                        "plan_id": row["id"],
                        "task": row["task"],
                        "status": row["status"],
                        "debate_id": row["debate_id"],
                        "created_at": row["created_at"],
                        "execution_status": row["exec_status"],
                        "execution_error": exec_error,
                    }
                )

            return outcomes
        finally:
            conn.close()

    def delete(self, plan_id: str) -> bool:
        """Delete a plan by ID. Returns True if deleted."""
        conn = self._connect()
        try:
            cursor = conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> DecisionPlan:
        """Convert a database row to a DecisionPlan."""
        row_keys = set(row.keys())
        budget_data = json.loads(row["budget_json"] or "{}")
        budget = BudgetAllocation(
            limit_usd=budget_data.get("limit_usd"),
            estimated_usd=budget_data.get("estimated_usd", 0.0),
            spent_usd=budget_data.get("spent_usd", 0.0),
            debate_cost_usd=budget_data.get("debate_cost_usd", 0.0),
            implementation_cost_usd=budget_data.get("implementation_cost_usd", 0.0),
            verification_cost_usd=budget_data.get("verification_cost_usd", 0.0),
        )

        approval_record = None
        if row["approval_record_json"]:
            ar_data = json.loads(row["approval_record_json"])
            approval_record = ApprovalRecord(
                approved=ar_data.get("approved", False),
                approver_id=ar_data.get("approver_id", ""),
                reason=ar_data.get("reason", ""),
                conditions=ar_data.get("conditions", []),
            )

        implementation_profile = None
        raw_profile = (
            row["implementation_profile_json"]
            if "implementation_profile_json" in row_keys
            else None
        )
        if raw_profile:
            try:
                profile_data = json.loads(raw_profile)
                if isinstance(profile_data, dict):
                    implementation_profile = ImplementationProfile.from_dict(profile_data)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "invalid implementation_profile_json for plan %s: %s", row["id"], exc
                )

        metadata = json.loads(row["metadata_json"] or "{}")
        risk_register = None
        if "risk_register_json" in row_keys and row["risk_register_json"]:
            try:
                risk_register = RiskRegister.from_dict(json.loads(row["risk_register_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("invalid risk_register_json for plan %s: %s", row["id"], exc)

        verification_plan = None
        if "verification_plan_json" in row_keys and row["verification_plan_json"]:
            try:
                verification_plan = VerificationPlan.from_dict(
                    json.loads(row["verification_plan_json"])
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("invalid verification_plan_json for plan %s: %s", row["id"], exc)

        implement_plan = None
        if "implement_plan_json" in row_keys and row["implement_plan_json"]:
            try:
                implement_plan = ImplementPlan.from_dict(json.loads(row["implement_plan_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("invalid implement_plan_json for plan %s: %s", row["id"], exc)

        max_auto_risk_raw = (
            row["max_auto_risk"] if "max_auto_risk" in row_keys else RiskLevel.LOW.value
        )
        try:
            max_auto_risk = RiskLevel(max_auto_risk_raw)
        except ValueError:
            max_auto_risk = RiskLevel.LOW

        created_at = datetime.fromisoformat(row["created_at"])

        plan = DecisionPlan(
            id=row["id"],
            debate_id=row["debate_id"],
            task=row["task"],
            status=PlanStatus(row["status"]),
            approval_mode=ApprovalMode(row["approval_mode"]),
            max_auto_risk=max_auto_risk,
            budget=budget,
            approval_record=approval_record,
            risk_register=risk_register,
            verification_plan=verification_plan,
            implement_plan=implement_plan,
            metadata=metadata,
            implementation_profile=implementation_profile,
            created_at=created_at,
        )

        return plan

    @staticmethod
    def _row_to_execution_record(row: sqlite3.Row) -> dict[str, Any]:
        """Convert execution row to dictionary payload."""
        error_payload = None
        if row["error_json"]:
            try:
                error_payload = json.loads(row["error_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                error_payload = {"message": str(row["error_json"])}

        metadata_payload: dict[str, Any] = {}
        if row["metadata_json"]:
            try:
                parsed = json.loads(row["metadata_json"])
                if isinstance(parsed, dict):
                    metadata_payload = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata_payload = {}

        return {
            "execution_id": row["execution_id"],
            "plan_id": row["plan_id"],
            "debate_id": row["debate_id"],
            "correlation_id": row["correlation_id"],
            "status": row["status"],
            "error": error_payload,
            "metadata": metadata_payload,
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: PlanStore | None = None


def get_plan_store() -> PlanStore:
    """Get or create the module-level PlanStore singleton."""
    global _store
    if _store is None:
        _store = PlanStore()
    return _store


__all__ = ["PlanStore", "get_plan_store"]
