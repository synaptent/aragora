"""
PostgresGovernanceStore - Async PostgreSQL persistence for decision governance artifacts.

Async implementation for production multi-instance deployments
with horizontal scaling and concurrent access to governance records.
Uses asyncpg connection pools for high-performance database access.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncpg import Pool

from aragora.utils.async_utils import run_async

from .metrics import (
    record_governance_approval,
    record_governance_decision,
    record_governance_verification,
)
from .models import ApprovalRecord, DecisionRecord, VerificationRecord

logger = logging.getLogger(__name__)


def _parse_epoch_datetime(val: Any) -> datetime:
    """Parse a datetime value from a PostgreSQL row (epoch or datetime)."""
    if val is None:
        return datetime.now()
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val)
    if isinstance(val, datetime):
        return val
    return datetime.now()


class PostgresGovernanceStore:
    """
    PostgreSQL-backed governance store.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent access to governance records.
    """

    SCHEMA_NAME = "governance"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS governance_approvals (
            approval_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            risk_level TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_by TEXT,
            requested_at TIMESTAMPTZ DEFAULT NOW(),
            changes_json JSONB,
            timeout_seconds INTEGER DEFAULT 3600,
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            rejection_reason TEXT,
            org_id TEXT,
            workspace_id TEXT,
            metadata_json JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_approvals_status ON governance_approvals(status);
        CREATE INDEX IF NOT EXISTS idx_approvals_org ON governance_approvals(org_id);
        CREATE INDEX IF NOT EXISTS idx_approvals_requested ON governance_approvals(requested_at DESC);

        CREATE TABLE IF NOT EXISTS governance_verifications (
            verification_id TEXT PRIMARY KEY,
            claim TEXT NOT NULL,
            claim_type TEXT,
            context TEXT,
            result_json JSONB NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            verified_by TEXT,
            confidence REAL DEFAULT 0,
            proof_tree_json JSONB,
            org_id TEXT,
            workspace_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_verifications_timestamp ON governance_verifications(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_verifications_org ON governance_verifications(org_id);

        CREATE TABLE IF NOT EXISTS governance_decisions (
            decision_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            conclusion TEXT,
            consensus_reached BOOLEAN,
            confidence REAL,
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            evidence_chain_json JSONB,
            vote_pivots_json JSONB,
            belief_changes_json JSONB,
            agents_involved_json JSONB,
            org_id TEXT,
            workspace_id TEXT,
            metadata_json JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_debate ON governance_decisions(debate_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_org ON governance_decisions(org_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON governance_decisions(timestamp DESC);
    """

    def __init__(self, pool: Pool):
        self._pool = pool
        self._initialized = False
        logger.info("PostgresGovernanceStore initialized")

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

    # =========================================================================
    # Approval Management
    # =========================================================================

    def save_approval(
        self,
        approval_id: str,
        title: str,
        description: str,
        risk_level: str,
        status: str,
        requested_by: str,
        changes: list,
        timeout_seconds: int = 3600,
        org_id: str | None = None,
        workspace_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Save a new approval request (sync wrapper for async)."""
        return run_async(
            self.save_approval_async(
                approval_id,
                title,
                description,
                risk_level,
                status,
                requested_by,
                changes,
                timeout_seconds,
                org_id,
                workspace_id,
                metadata,
            )
        )

    async def save_approval_async(
        self,
        approval_id: str,
        title: str,
        description: str,
        risk_level: str,
        status: str,
        requested_by: str,
        changes: list,
        timeout_seconds: int = 3600,
        org_id: str | None = None,
        workspace_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Save a new approval request asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO governance_approvals (
                    approval_id, title, description, risk_level, status,
                    requested_by, requested_at, changes_json, timeout_seconds,
                    org_id, workspace_id, metadata_json
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, $8, $9, $10, $11)
                ON CONFLICT (approval_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    metadata_json = EXCLUDED.metadata_json""",
                approval_id,
                title,
                description,
                risk_level,
                status,
                requested_by,
                json.dumps(changes),
                timeout_seconds,
                org_id,
                workspace_id,
                json.dumps(metadata or {}),
            )

        # Record metrics
        approval_type = "nomic" if "nomic" in title.lower() else "change"
        record_governance_approval(approval_type, status)

        logger.debug("Saved approval: %s", approval_id)
        return approval_id

    def update_approval_status(
        self,
        approval_id: str,
        status: str,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        """Update approval status (sync wrapper for async)."""
        return run_async(
            self.update_approval_status_async(approval_id, status, approved_by, rejection_reason)
        )

    async def update_approval_status_async(
        self,
        approval_id: str,
        status: str,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        """Update approval status asynchronously."""
        updates = ["status = $1"]
        params: list = [status]
        param_idx = 2

        if approved_by:
            updates.append(f"approved_by = ${param_idx}")
            params.append(approved_by)
            param_idx += 1
            updates.append("approved_at = NOW()")

        if rejection_reason:
            updates.append(f"rejection_reason = ${param_idx}")
            params.append(rejection_reason)
            param_idx += 1

        params.append(approval_id)

        async with self._pool.acquire() as conn:
            await conn.execute(
                # dynamic clause from internal state
                f"UPDATE governance_approvals SET {', '.join(updates)} WHERE approval_id = ${param_idx}",
                *params,
            )

        logger.debug("Updated approval %s -> %s", approval_id, status)
        return True

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        """Get an approval by ID (sync wrapper for async)."""
        return run_async(self.get_approval_async(approval_id))

    async def get_approval_async(self, approval_id: str) -> ApprovalRecord | None:
        """Get an approval by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT approval_id, title, description, risk_level, status,
                          requested_by,
                          EXTRACT(EPOCH FROM requested_at) as requested_at,
                          changes_json, timeout_seconds, approved_by,
                          EXTRACT(EPOCH FROM approved_at) as approved_at,
                          rejection_reason, org_id, workspace_id, metadata_json
                   FROM governance_approvals
                   WHERE approval_id = $1""",
                approval_id,
            )

        if not row:
            return None

        return self._row_to_approval(row)

    def list_approvals(
        self,
        status: str | None = None,
        org_id: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        """List approvals with filters (sync wrapper for async)."""
        return run_async(self.list_approvals_async(status, org_id, risk_level, limit))

    async def list_approvals_async(
        self,
        status: str | None = None,
        org_id: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        """List approvals asynchronously."""
        query = """SELECT approval_id, title, description, risk_level, status,
                          requested_by,
                          EXTRACT(EPOCH FROM requested_at) as requested_at,
                          changes_json, timeout_seconds, approved_by,
                          EXTRACT(EPOCH FROM approved_at) as approved_at,
                          rejection_reason, org_id, workspace_id, metadata_json
                   FROM governance_approvals
                   WHERE 1=1"""
        params: list = []
        param_idx = 1

        if status:
            query += f" AND status = ${param_idx}"
            params.append(status)
            param_idx += 1

        if org_id:
            query += f" AND org_id = ${param_idx}"
            params.append(org_id)
            param_idx += 1

        if risk_level:
            query += f" AND risk_level = ${param_idx}"
            params.append(risk_level)
            param_idx += 1

        query += f" ORDER BY requested_at DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_approval(row) for row in rows]

    def delete_approval(self, approval_id: str) -> bool:
        """Delete an approval record (sync wrapper for async)."""
        return run_async(self.delete_approval_async(approval_id))

    async def delete_approval_async(self, approval_id: str) -> bool:
        """Delete an approval record asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM governance_approvals WHERE approval_id = $1",
                approval_id,
            )
        return True

    def _row_to_approval(self, row: Any) -> ApprovalRecord:
        """Convert database row to ApprovalRecord."""
        return ApprovalRecord(
            approval_id=row["approval_id"],
            title=row["title"],
            description=row["description"] or "",
            risk_level=row["risk_level"],
            status=row["status"],
            requested_by=row["requested_by"] or "",
            requested_at=_parse_epoch_datetime(row["requested_at"]),
            changes_json=(
                row["changes_json"]
                if isinstance(row["changes_json"], str)
                else json.dumps(row["changes_json"] or [])
            ),
            timeout_seconds=row["timeout_seconds"] or 3600,
            approved_by=row["approved_by"],
            approved_at=_parse_epoch_datetime(row["approved_at"]) if row["approved_at"] else None,
            rejection_reason=row["rejection_reason"],
            org_id=row["org_id"],
            workspace_id=row["workspace_id"],
            metadata_json=(
                row["metadata_json"]
                if isinstance(row["metadata_json"], str)
                else json.dumps(row["metadata_json"] or {})
            ),
        )

    # =========================================================================
    # Verification History
    # =========================================================================

    def save_verification(
        self,
        verification_id: str,
        claim: str,
        context: str,
        result: dict,
        verified_by: str = "system",
        claim_type: str | None = None,
        confidence: float = 0.0,
        proof_tree: list | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Save a verification result (sync wrapper for async)."""
        return run_async(
            self.save_verification_async(
                verification_id,
                claim,
                context,
                result,
                verified_by,
                claim_type,
                confidence,
                proof_tree,
                org_id,
                workspace_id,
            )
        )

    async def save_verification_async(
        self,
        verification_id: str,
        claim: str,
        context: str,
        result: dict,
        verified_by: str = "system",
        claim_type: str | None = None,
        confidence: float = 0.0,
        proof_tree: list | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """Save a verification result asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO governance_verifications (
                    verification_id, claim, claim_type, context, result_json,
                    timestamp, verified_by, confidence, proof_tree_json,
                    org_id, workspace_id
                )
                VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7, $8, $9, $10)
                ON CONFLICT (verification_id) DO UPDATE SET
                    result_json = EXCLUDED.result_json,
                    confidence = EXCLUDED.confidence""",
                verification_id,
                claim,
                claim_type,
                context,
                json.dumps(result),
                verified_by,
                confidence,
                json.dumps(proof_tree) if proof_tree else None,
                org_id,
                workspace_id,
            )

        # Record metrics
        verification_type = claim_type or "formal"
        verification_result = "valid" if result.get("valid", False) else "invalid"
        record_governance_verification(verification_type, verification_result)

        logger.debug("Saved verification: %s", verification_id)
        return verification_id

    def get_verification(self, verification_id: str) -> VerificationRecord | None:
        """Get a verification by ID (sync wrapper for async)."""
        return run_async(self.get_verification_async(verification_id))

    async def get_verification_async(self, verification_id: str) -> VerificationRecord | None:
        """Get a verification by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT verification_id, claim, claim_type, context, result_json,
                          EXTRACT(EPOCH FROM timestamp) as timestamp,
                          verified_by, confidence, proof_tree_json,
                          org_id, workspace_id
                   FROM governance_verifications
                   WHERE verification_id = $1""",
                verification_id,
            )

        if not row:
            return None

        return self._row_to_verification(row)

    def list_verifications(
        self,
        org_id: str | None = None,
        claim_type: str | None = None,
        limit: int = 100,
    ) -> list[VerificationRecord]:
        """List verifications with filters (sync wrapper for async)."""
        return run_async(self.list_verifications_async(org_id, claim_type, limit))

    async def list_verifications_async(
        self,
        org_id: str | None = None,
        claim_type: str | None = None,
        limit: int = 100,
    ) -> list[VerificationRecord]:
        """List verifications asynchronously."""
        query = """SELECT verification_id, claim, claim_type, context, result_json,
                          EXTRACT(EPOCH FROM timestamp) as timestamp,
                          verified_by, confidence, proof_tree_json,
                          org_id, workspace_id
                   FROM governance_verifications
                   WHERE 1=1"""
        params: list = []
        param_idx = 1

        if org_id:
            query += f" AND org_id = ${param_idx}"
            params.append(org_id)
            param_idx += 1

        if claim_type:
            query += f" AND claim_type = ${param_idx}"
            params.append(claim_type)
            param_idx += 1

        query += f" ORDER BY timestamp DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_verification(row) for row in rows]

    def _row_to_verification(self, row: Any) -> VerificationRecord:
        """Convert database row to VerificationRecord."""
        return VerificationRecord(
            verification_id=row["verification_id"],
            claim=row["claim"],
            claim_type=row["claim_type"],
            context=row["context"] or "",
            result_json=(
                row["result_json"]
                if isinstance(row["result_json"], str)
                else json.dumps(row["result_json"] or {})
            ),
            timestamp=_parse_epoch_datetime(row["timestamp"]),
            verified_by=row["verified_by"] or "system",
            confidence=row["confidence"] or 0.0,
            proof_tree_json=(
                row["proof_tree_json"]
                if isinstance(row["proof_tree_json"], str)
                else json.dumps(row["proof_tree_json"])
                if row["proof_tree_json"]
                else None
            ),
            org_id=row["org_id"],
            workspace_id=row["workspace_id"],
        )

    # =========================================================================
    # Decision Records
    # =========================================================================

    def save_decision(
        self,
        decision_id: str,
        debate_id: str,
        conclusion: str,
        consensus_reached: bool,
        confidence: float,
        evidence_chain: list | None = None,
        vote_pivots: list | None = None,
        belief_changes: list | None = None,
        agents_involved: list | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Save a decision record (sync wrapper for async)."""
        return run_async(
            self.save_decision_async(
                decision_id,
                debate_id,
                conclusion,
                consensus_reached,
                confidence,
                evidence_chain,
                vote_pivots,
                belief_changes,
                agents_involved,
                org_id,
                workspace_id,
                metadata,
            )
        )

    async def save_decision_async(
        self,
        decision_id: str,
        debate_id: str,
        conclusion: str,
        consensus_reached: bool,
        confidence: float,
        evidence_chain: list | None = None,
        vote_pivots: list | None = None,
        belief_changes: list | None = None,
        agents_involved: list | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Save a decision record asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO governance_decisions (
                    decision_id, debate_id, conclusion, consensus_reached,
                    confidence, timestamp, evidence_chain_json, vote_pivots_json,
                    belief_changes_json, agents_involved_json, org_id,
                    workspace_id, metadata_json
                )
                VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (decision_id) DO UPDATE SET
                    conclusion = EXCLUDED.conclusion,
                    confidence = EXCLUDED.confidence""",
                decision_id,
                debate_id,
                conclusion,
                consensus_reached,
                confidence,
                json.dumps(evidence_chain or []),
                json.dumps(vote_pivots or []),
                json.dumps(belief_changes or []),
                json.dumps(agents_involved or []),
                org_id,
                workspace_id,
                json.dumps(metadata or {}),
            )

        # Record metrics
        decision_type = "auto"
        outcome = "approved" if consensus_reached else "rejected"
        record_governance_decision(decision_type, outcome)

        logger.debug("Saved decision: %s", decision_id)
        return decision_id

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        """Get a decision by ID (sync wrapper for async)."""
        return run_async(self.get_decision_async(decision_id))

    async def get_decision_async(self, decision_id: str) -> DecisionRecord | None:
        """Get a decision by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT decision_id, debate_id, conclusion, consensus_reached,
                          confidence, EXTRACT(EPOCH FROM timestamp) as timestamp,
                          evidence_chain_json, vote_pivots_json,
                          belief_changes_json, agents_involved_json, org_id,
                          workspace_id, metadata_json
                   FROM governance_decisions
                   WHERE decision_id = $1""",
                decision_id,
            )

        if not row:
            return None

        return self._row_to_decision(row)

    def get_decisions_for_debate(self, debate_id: str) -> list[DecisionRecord]:
        """Get all decisions for a debate (sync wrapper for async)."""
        return run_async(self.get_decisions_for_debate_async(debate_id))

    async def get_decisions_for_debate_async(self, debate_id: str) -> list[DecisionRecord]:
        """Get all decisions for a debate asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT decision_id, debate_id, conclusion, consensus_reached,
                          confidence, EXTRACT(EPOCH FROM timestamp) as timestamp,
                          evidence_chain_json, vote_pivots_json,
                          belief_changes_json, agents_involved_json, org_id,
                          workspace_id, metadata_json
                   FROM governance_decisions
                   WHERE debate_id = $1
                   ORDER BY timestamp DESC""",
                debate_id,
            )
            return [self._row_to_decision(row) for row in rows]

    def list_decisions(
        self,
        org_id: str | None = None,
        consensus_only: bool = False,
        limit: int = 100,
    ) -> list[DecisionRecord]:
        """List decisions with filters (sync wrapper for async)."""
        return run_async(self.list_decisions_async(org_id, consensus_only, limit))

    async def list_decisions_async(
        self,
        org_id: str | None = None,
        consensus_only: bool = False,
        limit: int = 100,
    ) -> list[DecisionRecord]:
        """List decisions asynchronously."""
        query = """SELECT decision_id, debate_id, conclusion, consensus_reached,
                          confidence, EXTRACT(EPOCH FROM timestamp) as timestamp,
                          evidence_chain_json, vote_pivots_json,
                          belief_changes_json, agents_involved_json, org_id,
                          workspace_id, metadata_json
                   FROM governance_decisions
                   WHERE 1=1"""
        params: list = []
        param_idx = 1

        if org_id:
            query += f" AND org_id = ${param_idx}"
            params.append(org_id)
            param_idx += 1

        if consensus_only:
            query += " AND consensus_reached = TRUE"

        query += f" ORDER BY timestamp DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_decision(row) for row in rows]

    def _row_to_decision(self, row: Any) -> DecisionRecord:
        """Convert database row to DecisionRecord."""

        def to_json_str(val: Any) -> str:
            if val is None:
                return "[]"
            if isinstance(val, str):
                return val
            return json.dumps(val)

        return DecisionRecord(
            decision_id=row["decision_id"],
            debate_id=row["debate_id"],
            conclusion=row["conclusion"] or "",
            consensus_reached=bool(row["consensus_reached"]),
            confidence=row["confidence"] or 0.0,
            timestamp=_parse_epoch_datetime(row["timestamp"]),
            evidence_chain_json=to_json_str(row["evidence_chain_json"]),
            vote_pivots_json=to_json_str(row["vote_pivots_json"]),
            belief_changes_json=to_json_str(row["belief_changes_json"]),
            agents_involved_json=to_json_str(row["agents_involved_json"]),
            org_id=row["org_id"],
            workspace_id=row["workspace_id"],
            metadata_json=(
                row["metadata_json"]
                if isinstance(row["metadata_json"], str)
                else json.dumps(row["metadata_json"] or {})
            ),
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def cleanup_old_records(
        self,
        approvals_days: int = 30,
        verifications_days: int = 7,
        decisions_days: int = 90,
    ) -> dict:
        """Clean up old records (sync wrapper for async)."""
        return run_async(
            self.cleanup_old_records_async(approvals_days, verifications_days, decisions_days)
        )

    async def cleanup_old_records_async(
        self,
        approvals_days: int = 30,
        verifications_days: int = 7,
        decisions_days: int = 90,
    ) -> dict:
        """Clean up old records asynchronously.

        Uses explicit transaction for atomic cleanup across multiple tables.
        """
        counts = {}

        async with self._pool.acquire() as conn:
            # Use explicit transaction for atomic multi-table cleanup
            async with conn.transaction():
                # Count and delete approvals
                result = await conn.fetchrow(
                    """SELECT COUNT(*) as count FROM governance_approvals
                       WHERE status IN ('approved', 'rejected', 'expired', 'cancelled')
                       AND requested_at < NOW() - INTERVAL '1 day' * $1""",
                    approvals_days,
                )
                counts["approvals"] = result["count"] if result else 0

                if counts["approvals"] > 0:
                    await conn.execute(
                        """DELETE FROM governance_approvals
                           WHERE status IN ('approved', 'rejected', 'expired', 'cancelled')
                           AND requested_at < NOW() - INTERVAL '1 day' * $1""",
                        approvals_days,
                    )

                # Count and delete verifications
                result = await conn.fetchrow(
                    """SELECT COUNT(*) as count FROM governance_verifications
                       WHERE timestamp < NOW() - INTERVAL '1 day' * $1""",
                    verifications_days,
                )
                counts["verifications"] = result["count"] if result else 0

                if counts["verifications"] > 0:
                    await conn.execute(
                        """DELETE FROM governance_verifications
                           WHERE timestamp < NOW() - INTERVAL '1 day' * $1""",
                        verifications_days,
                    )

        logger.info("Cleaned up governance records: %s", counts)
        return counts

    def close(self) -> None:
        """Close is a no-op for pool-based stores (pool managed externally)."""
        pass


__all__ = [
    "PostgresGovernanceStore",
]
