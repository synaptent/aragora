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
from typing import Any, Iterable, Sequence
import uuid

from aragora.pipeline.backbone_contracts import (
    DeliberationBundle,
    IntakeBundle,
    OutcomeFeedbackRecord,
    ReceiptEnvelope,
    RunLedger,
    RunStageEvent,
    SpecBundle,
)
from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    ApprovalRecord,
    BudgetAllocation,
    DecisionPlan,
    ImplementationProfile,
    PlanStatus,
)
from aragora.pipeline.plan_ownership import ensure_ownership_columns, migrate_plan_store_schema
from aragora.pipeline.risk_register import RiskLevel, RiskRegister
from aragora.pipeline.verification_plan import VerificationPlan
from aragora.implement.types import ImplementPlan
from aragora.tenancy.membership import MembershipLookupError, OrgMembershipResolver, user_org_ids

logger = logging.getLogger(__name__)

# Default database location
_DEFAULT_DB_DIR = os.environ.get("ARAGORA_DATA_DIR", str(Path.home() / ".aragora"))
_DEFAULT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "plans.db")
_UNSET = object()


def _get_db_path() -> str:
    """Resolve the plan store database path."""
    try:
        from aragora.persistence.db_config import get_default_data_dir

        return str(get_default_data_dir() / "plans.db")
    except ImportError:
        return _DEFAULT_DB_PATH


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    """Preserve order while removing blank or duplicate string-like values."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _parse_metadata_json(raw: str | None) -> dict[str, Any]:
    """Parse metadata JSON safely into a dictionary."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_json_value(raw: str | None) -> Any:
    """Parse arbitrary JSON payloads safely."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _extract_refresh_scope(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract canonical refresh hints from plan metadata."""
    refresh = metadata.get("assessment_refresh")
    if not isinstance(refresh, dict):
        refresh = {}

    work_orders = metadata.get("bounded_work_orders")
    if not isinstance(work_orders, list):
        work_orders = []

    files = _dedupe_strings(refresh.get("files_to_reassess", []))
    tests = _dedupe_strings(refresh.get("test_commands", []))
    work_order_ids = _dedupe_strings(refresh.get("work_order_ids", []))
    approval_required = bool(refresh.get("approval_required", False))

    if not files:
        files = _dedupe_strings(
            path
            for work_order in work_orders
            if isinstance(work_order, dict)
            for path in work_order.get("file_scope", [])
        )
    if not tests:
        tests = _dedupe_strings(
            test
            for work_order in work_orders
            if isinstance(work_order, dict)
            for test in work_order.get("expected_tests", [])
        )
    if not work_order_ids:
        work_order_ids = _dedupe_strings(
            work_order.get("work_order_id", "")
            for work_order in work_orders
            if isinstance(work_order, dict)
        )
    if not approval_required:
        approval_required = any(
            bool(work_order.get("approval_required"))
            for work_order in work_orders
            if isinstance(work_order, dict)
        )

    refresh_required = bool(refresh.get("required", False) or files or tests or work_order_ids)
    refresh_reason = refresh.get("reason")
    if not isinstance(refresh_reason, str) or not refresh_reason.strip():
        refresh_reason = "bounded_work_orders_changed_repo_truth" if refresh_required else ""

    return {
        "refresh_required": refresh_required,
        "refresh_reason": refresh_reason,
        "affected_files": files,
        "expected_tests": tests,
        "work_order_ids": work_order_ids,
        "approval_required": approval_required,
        "source": metadata.get("source"),
    }


class PlanStore:
    """SQLite-backed store for DecisionPlan objects.

    Thread-safe via SQLite WAL mode. Each method creates its own
    connection to support concurrent access from handler threads.

    Plans, execution records and runs carry ``org_id``/``created_by``/
    ``ownership_source`` (see ``aragora.pipeline.plan_ownership``).
    ``org_membership_resolver`` maps a user id to its org ids for the one-time
    ownership backfill (default: the user store).
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        org_membership_resolver: OrgMembershipResolver | None = None,
    ) -> None:
        self._db_path = db_path or _get_db_path()
        self._resolve_org_ids = org_membership_resolver or user_org_ids
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backbone_runs (
                    run_id TEXT PRIMARY KEY,
                    entrypoint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'received',
                    intake_bundle_json TEXT,
                    spec_bundle_json TEXT,
                    goal_refs_json TEXT,
                    deliberation_bundle_json TEXT,
                    plan_id TEXT,
                    debate_id TEXT,
                    execution_id TEXT,
                    receipt_id TEXT,
                    receipt_envelope_json TEXT,
                    feedback_record_json TEXT,
                    attestation_json TEXT,
                    taint_flags_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backbone_runs_status
                ON backbone_runs(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backbone_runs_plan_id
                ON backbone_runs(plan_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backbone_runs_debate_id
                ON backbone_runs(debate_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backbone_runs_execution_id
                ON backbone_runs(execution_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backbone_run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_ref TEXT,
                    details_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES backbone_runs(run_id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backbone_run_events_run_id
                ON backbone_run_events(run_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backbone_run_events_stage
                ON backbone_run_events(stage)
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
            ensure_ownership_columns(conn)
            try:
                migrate_plan_store_schema(conn, self._resolve_org_ids)
            except MembershipLookupError as exc:
                conn.rollback()
                logger.warning(
                    "plans.db ownership backfill deferred until the user store is reachable: %s",
                    exc,
                )
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
        metadata_json = (
            json.dumps(
                plan.metadata,
                default=lambda o: o.to_dict() if hasattr(o, "to_dict") else str(o),
            )
            if plan.metadata
            else "{}"
        )

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

    def save(self, plan: DecisionPlan) -> bool:
        """Persist the full current state of an existing plan."""
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
        metadata_json = (
            json.dumps(
                plan.metadata,
                default=lambda o: o.to_dict() if hasattr(o, "to_dict") else str(o),
            )
            if plan.metadata
            else "{}"
        )
        approved_by = plan.approval_record.approver_id if plan.approval_record else None
        rejection_reason = (
            plan.approval_record.reason
            if plan.approval_record and not plan.approval_record.approved
            else None
        )
        approved_at = (
            plan.approval_record.timestamp.isoformat()
            if plan.approval_record and plan.approval_record.approved
            else None
        )

        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE plans
                SET debate_id = ?,
                    task = ?,
                    status = ?,
                    approval_mode = ?,
                    max_auto_risk = ?,
                    approved_by = ?,
                    rejection_reason = ?,
                    approved_at = ?,
                    budget_json = ?,
                    approval_record_json = ?,
                    implementation_profile_json = ?,
                    risk_register_json = ?,
                    verification_plan_json = ?,
                    implement_plan_json = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    plan.debate_id,
                    plan.task,
                    plan.status.value,
                    plan.approval_mode.value,
                    plan.max_auto_risk.value,
                    approved_by,
                    rejection_reason,
                    approved_at,
                    budget_json,
                    approval_json,
                    implementation_profile_json,
                    risk_register_json,
                    verification_plan_json,
                    implement_plan_json,
                    metadata_json,
                    now,
                    plan.id,
                ),
            )
            conn.commit()
            updated = cursor.rowcount > 0
        finally:
            conn.close()

        if updated and plan.status in (
            PlanStatus.APPROVED,
            PlanStatus.REJECTED,
            PlanStatus.COMPLETED,
        ):
            try:
                from aragora.pipeline.receipt_gate import sync_plan_receipt_state

                sync_plan_receipt_state(plan, on_status=plan.status)
            except Exception as exc:  # noqa: BLE001 - do not mask save
                logger.warning(
                    "Failed to synchronize decision receipt for plan %s: %s",
                    plan.id,
                    exc,
                )
        return updated

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
            existing = self.get_execution_record(execution_id)
            merged_metadata = dict(existing.get("metadata", {}) or {}) if existing else {}
            merged_metadata.update(metadata)
            fields.append("metadata_json = ?")
            params.append(json.dumps(merged_metadata))

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
                       p.metadata_json,
                       e.status AS exec_status,
                       e.error_json AS exec_error
                FROM plans p
                LEFT JOIN plan_executions e ON e.execution_id = (
                    SELECT pe.execution_id
                    FROM plan_executions pe
                    WHERE pe.plan_id = p.id
                    ORDER BY COALESCE(pe.completed_at, pe.updated_at, pe.started_at) DESC,
                             pe.execution_id DESC
                    LIMIT 1
                )
                WHERE p.status IN ('completed', 'failed', 'rejected')
                ORDER BY COALESCE(p.updated_at, p.created_at) DESC
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
                metadata = _parse_metadata_json(row["metadata_json"])
                refresh_scope = _extract_refresh_scope(metadata)

                outcomes.append(
                    {
                        "plan_id": row["id"],
                        "task": row["task"],
                        "status": row["status"],
                        "debate_id": row["debate_id"],
                        "created_at": row["created_at"],
                        "execution_status": row["exec_status"],
                        "execution_error": exec_error,
                        **refresh_scope,
                    }
                )

            return outcomes
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Backbone run ledger
    # -------------------------------------------------------------------------

    def create_run(self, run: RunLedger) -> None:
        """Insert a new persisted backbone run ledger."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO backbone_runs (
                    run_id, entrypoint, status, intake_bundle_json, spec_bundle_json,
                    goal_refs_json, deliberation_bundle_json, plan_id, debate_id,
                    execution_id, receipt_id, receipt_envelope_json, feedback_record_json,
                    attestation_json, taint_flags_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.entrypoint,
                    run.status,
                    json.dumps(run.intake_bundle.to_dict()) if run.intake_bundle else None,
                    json.dumps(run.spec_bundle.to_dict()) if run.spec_bundle else None,
                    json.dumps(run.goal_refs),
                    json.dumps(run.deliberation_bundle.to_dict())
                    if run.deliberation_bundle
                    else None,
                    run.plan_id or None,
                    run.debate_id or None,
                    run.execution_id or None,
                    run.receipt_id or None,
                    json.dumps(run.receipt_envelope.to_dict()) if run.receipt_envelope else None,
                    json.dumps(run.feedback_record.to_dict()) if run.feedback_record else None,
                    json.dumps(run.attestation),
                    json.dumps(run.taint_flags),
                    json.dumps(run.metadata),
                    run.created_at,
                    run.updated_at,
                ),
            )
            for event in run.stage_events:
                conn.execute(
                    """
                    INSERT INTO backbone_run_events (
                        event_id, run_id, stage, status, artifact_ref, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        run.run_id,
                        event.stage,
                        event.status,
                        event.artifact_ref or None,
                        json.dumps(event.details),
                        event.created_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_run(self, run_id: str) -> RunLedger | None:
        """Fetch one backbone run ledger by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM backbone_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            event_rows = conn.execute(
                """
                SELECT * FROM backbone_run_events
                WHERE run_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (run_id,),
            ).fetchall()
            return self._row_to_run(row, event_rows)
        finally:
            conn.close()

    def list_runs(
        self,
        *,
        status: str | None = None,
        plan_id: str | None = None,
        debate_id: str | None = None,
        execution_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[RunLedger]:
        """List backbone run ledgers with optional filters."""
        clauses: builtins.list[str] = []
        params: builtins.list[Any] = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if plan_id is not None:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if debate_id is not None:
            clauses.append("debate_id = ?")
            params.append(debate_id)
        if execution_id is not None:
            clauses.append("execution_id = ?")
            params.append(execution_id)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        query = f"SELECT * FROM backbone_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"  # noqa: S608 -- internal query construction
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            results: builtins.list[RunLedger] = []
            for row in rows:
                event_rows = conn.execute(
                    """
                    SELECT * FROM backbone_run_events
                    WHERE run_id = ?
                    ORDER BY created_at ASC, event_id ASC
                    """,
                    (row["run_id"],),
                ).fetchall()
                results.append(self._row_to_run(row, event_rows))
            return results
        finally:
            conn.close()

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        intake_bundle: IntakeBundle | None | object = _UNSET,
        spec_bundle: SpecBundle | None | object = _UNSET,
        goal_refs: builtins.list[dict[str, Any]] | object = _UNSET,
        deliberation_bundle: DeliberationBundle | None | object = _UNSET,
        plan_id: str | None = None,
        debate_id: str | None = None,
        execution_id: str | None = None,
        receipt_id: str | None = None,
        receipt_envelope: ReceiptEnvelope | None | object = _UNSET,
        feedback_record: OutcomeFeedbackRecord | None | object = _UNSET,
        attestation: dict[str, Any] | object = _UNSET,
        taint_flags: builtins.list[str] | None | object = _UNSET,
        metadata: dict[str, Any] | object = _UNSET,
        merge_metadata: bool = True,
    ) -> bool:
        """Update one run ledger in-place."""
        run = self.get_run(run_id)
        if run is None:
            return False

        if status is not None:
            run.status = str(status).strip() or run.status
        if intake_bundle is not _UNSET:
            run.attach_intake(intake_bundle if isinstance(intake_bundle, IntakeBundle) else None)
        if spec_bundle is not _UNSET:
            run.attach_spec(spec_bundle if isinstance(spec_bundle, SpecBundle) else None)
        if goal_refs is not _UNSET:
            run.goal_refs = list(goal_refs) if isinstance(goal_refs, list) else []
            run.touch()
        if deliberation_bundle is not _UNSET:
            run.attach_deliberation(
                deliberation_bundle if isinstance(deliberation_bundle, DeliberationBundle) else None
            )
        if plan_id is not None:
            run.plan_id = str(plan_id).strip()
            run.touch()
        if debate_id is not None:
            run.debate_id = str(debate_id).strip()
            run.touch()
        if execution_id is not None:
            run.execution_id = str(execution_id).strip()
            run.touch()
        if receipt_id is not None:
            run.receipt_id = str(receipt_id).strip()
            run.touch()
        if receipt_envelope is not _UNSET:
            run.attach_receipt(
                receipt_envelope if isinstance(receipt_envelope, ReceiptEnvelope) else None
            )
        if feedback_record is not _UNSET:
            run.attach_feedback(
                feedback_record if isinstance(feedback_record, OutcomeFeedbackRecord) else None
            )
        if attestation is not _UNSET:
            run.attestation = dict(attestation) if isinstance(attestation, dict) else {}
            run.touch()
        if taint_flags is not _UNSET:
            run.merge_taint(list(taint_flags) if isinstance(taint_flags, list | tuple) else [])
        if metadata is not _UNSET:
            next_metadata = dict(metadata) if isinstance(metadata, dict) else {}
            if merge_metadata:
                run.metadata.update(next_metadata)
            else:
                run.metadata = next_metadata
            run.touch()

        run.touch()
        return self._save_run(run)

    def append_run_stage_event(self, run_id: str, event: RunStageEvent) -> bool:
        """Append a single stage event to a run."""
        conn = self._connect()
        try:
            try:
                conn.execute(
                    """
                    INSERT INTO backbone_run_events (
                        event_id, run_id, stage, status, artifact_ref, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        run_id,
                        event.stage,
                        event.status,
                        event.artifact_ref or None,
                        json.dumps(event.details),
                        event.created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                return False

            cursor = conn.execute(
                "UPDATE backbone_runs SET updated_at = ? WHERE run_id = ?",
                (event.created_at, run_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_run_stage_events(self, run_id: str) -> builtins.list[RunStageEvent]:
        """List all persisted stage events for a run."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM backbone_run_events
                WHERE run_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (run_id,),
            ).fetchall()
            return [self._row_to_run_event(row) for row in rows]
        finally:
            conn.close()

    def approve_run(
        self,
        run_id: str,
        *,
        approved_by: str = "unknown",
        reason: str = "",
    ) -> bool:
        """Approve a run currently in ``pending_approval`` status.

        Atomically transitions the run status from ``pending_approval`` to
        ``approved`` and records the approval metadata.  Returns ``True`` when
        the transition was applied, ``False`` when the run was not found or
        was not in ``pending_approval``.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            # Read current metadata so we can merge approval info
            row = conn.execute(
                "SELECT metadata_json FROM backbone_runs WHERE run_id = ? AND status = ?",
                (run_id, "pending_approval"),
            ).fetchone()
            if row is None:
                return False

            existing_metadata = _parse_metadata_json(row["metadata_json"])
            existing_metadata["approval"] = {
                "approved_by": approved_by,
                "reason": reason,
                "approved_at": now,
            }

            cursor = conn.execute(
                """
                UPDATE backbone_runs
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                ("approved", json.dumps(existing_metadata), now, run_id, "pending_approval"),
            )
            conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info("Approved run %s by %s", run_id, approved_by)
            return updated
        finally:
            conn.close()

    def resume_run(
        self,
        run_id: str,
        *,
        approved_by: str = "unknown",
        reason: str = "",
    ) -> bool:
        """Approve **and** resume a run currently in ``pending_approval``.

        Combines approval with an immediate status transition to ``running``
        so that the orchestrator can continue execution.  Returns ``True``
        when the transition was applied.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT metadata_json FROM backbone_runs WHERE run_id = ? AND status = ?",
                (run_id, "pending_approval"),
            ).fetchone()
            if row is None:
                return False

            existing_metadata = _parse_metadata_json(row["metadata_json"])
            existing_metadata["approval"] = {
                "approved_by": approved_by,
                "reason": reason,
                "approved_at": now,
            }
            existing_metadata["resumed_at"] = now

            cursor = conn.execute(
                """
                UPDATE backbone_runs
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                ("running", json.dumps(existing_metadata), now, run_id, "pending_approval"),
            )
            conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info("Approved and resumed run %s by %s", run_id, approved_by)
            return updated
        finally:
            conn.close()

    def reject_run(
        self,
        run_id: str,
        *,
        rejected_by: str = "unknown",
        reason: str = "",
    ) -> bool:
        """Reject a run currently in ``pending_approval`` status.

        Atomically transitions the run from ``pending_approval`` to
        ``rejected``.  Returns ``True`` when the transition was applied.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT metadata_json FROM backbone_runs WHERE run_id = ? AND status = ?",
                (run_id, "pending_approval"),
            ).fetchone()
            if row is None:
                return False

            existing_metadata = _parse_metadata_json(row["metadata_json"])
            existing_metadata["rejection"] = {
                "rejected_by": rejected_by,
                "reason": reason,
                "rejected_at": now,
            }

            cursor = conn.execute(
                """
                UPDATE backbone_runs
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                ("rejected", json.dumps(existing_metadata), now, run_id, "pending_approval"),
            )
            conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info("Rejected run %s by %s", run_id, rejected_by)
            return updated
        finally:
            conn.close()

    def list_pending_approval_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[RunLedger]:
        """List all runs currently waiting for approval."""
        return self.list_runs(status="pending_approval", limit=limit, offset=offset)

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

    def _save_run(self, run: RunLedger) -> bool:
        """Persist the current snapshot of a run ledger."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE backbone_runs
                SET entrypoint = ?,
                    status = ?,
                    intake_bundle_json = ?,
                    spec_bundle_json = ?,
                    goal_refs_json = ?,
                    deliberation_bundle_json = ?,
                    plan_id = ?,
                    debate_id = ?,
                    execution_id = ?,
                    receipt_id = ?,
                    receipt_envelope_json = ?,
                    feedback_record_json = ?,
                    attestation_json = ?,
                    taint_flags_json = ?,
                    metadata_json = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    run.entrypoint,
                    run.status,
                    json.dumps(run.intake_bundle.to_dict()) if run.intake_bundle else None,
                    json.dumps(run.spec_bundle.to_dict()) if run.spec_bundle else None,
                    json.dumps(run.goal_refs),
                    json.dumps(run.deliberation_bundle.to_dict())
                    if run.deliberation_bundle
                    else None,
                    run.plan_id or None,
                    run.debate_id or None,
                    run.execution_id or None,
                    run.receipt_id or None,
                    json.dumps(run.receipt_envelope.to_dict()) if run.receipt_envelope else None,
                    json.dumps(run.feedback_record.to_dict()) if run.feedback_record else None,
                    json.dumps(run.attestation),
                    json.dumps(run.taint_flags),
                    json.dumps(run.metadata),
                    run.updated_at,
                    run.run_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_run_event(row: sqlite3.Row) -> RunStageEvent:
        details = _load_json_value(row["details_json"])
        return RunStageEvent.from_dict(
            {
                "event_id": row["event_id"],
                "stage": row["stage"],
                "status": row["status"],
                "artifact_ref": row["artifact_ref"] or "",
                "details": details if isinstance(details, dict) else {},
                "created_at": row["created_at"],
            }
        )

    @staticmethod
    def _row_to_run(
        row: sqlite3.Row,
        event_rows: Sequence[sqlite3.Row] | None = None,
    ) -> RunLedger:
        return RunLedger.from_dict(
            {
                "run_id": row["run_id"],
                "entrypoint": row["entrypoint"],
                "status": row["status"],
                "intake_bundle": _load_json_value(row["intake_bundle_json"]),
                "spec_bundle": _load_json_value(row["spec_bundle_json"]),
                "goal_refs": _load_json_value(row["goal_refs_json"]) or [],
                "deliberation_bundle": _load_json_value(row["deliberation_bundle_json"]),
                "plan_id": row["plan_id"] or "",
                "debate_id": row["debate_id"] or "",
                "execution_id": row["execution_id"] or "",
                "receipt_id": row["receipt_id"] or "",
                "receipt_envelope": _load_json_value(row["receipt_envelope_json"]),
                "feedback_record": _load_json_value(row["feedback_record_json"]),
                "attestation": _load_json_value(row["attestation_json"]) or {},
                "taint_flags": _load_json_value(row["taint_flags_json"]) or [],
                "metadata": _parse_metadata_json(row["metadata_json"]),
                "stage_events": [
                    PlanStore._row_to_run_event(event_row).to_dict()
                    for event_row in list(event_rows or [])
                ],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )


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


__all__ = [
    "PlanStore",
    "get_plan_store",
]  # approve_run, resume_run, reject_run are PlanStore methods
