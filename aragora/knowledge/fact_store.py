"""
Fact Store - SQLite-based persistence for the Knowledge Base.

Provides storage, retrieval, and search for facts extracted from
documents and verified through multi-agent consensus.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, overload

from aragora.config import resolve_db_path

from aragora.knowledge.types import (
    Fact,
    FactFilters,
    FactRelation,
    FactRelationType,
    ValidationStatus,
)
from aragora.storage.base_store import SQLiteStore
from aragora.storage.fts_utils import sanitize_fts_query
from aragora.storage.schema import SchemaManager, safe_add_column

logger = logging.getLogger(__name__)


def _require_org(org_id: object) -> str:
    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("org_id must be a non-empty string")
    return org_id


def _org_clause(org_id: str | None, column: str = "org_id") -> tuple[str, tuple[str, ...]]:
    """SQL suffix and params restricting rows to one org; empty when unscoped."""
    if org_id is None:
        return "", ()
    return f" AND {column} = ?", (_require_org(org_id),)


def _add_org_scope(conn: sqlite3.Connection) -> None:
    """Schema v1 -> v2: nullable facts.org_id plus the org scope indexes.

    Existing rows keep org_id NULL (unassigned, invisible to org-scoped
    callers) until an operator runs FactStore.assign_org. safe_add_column and
    IF NOT EXISTS make a re-run after an interrupted migration harmless.
    """
    safe_add_column(conn, "facts", "org_id", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_facts_org_workspace ON facts(org_id, workspace_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_facts_org_scope_hash "
        "ON facts(org_id, workspace_id, statement_hash)"
    )


class FactStore(SQLiteStore):
    """SQLite-based fact persistence store.

    Stores facts extracted from documents along with their
    validation status, evidence links, and relationships.
    """

    SCHEMA_NAME = "fact_store"
    SCHEMA_VERSION = 2

    # The v1 layout. Fresh and legacy files both reach v2 through
    # register_migrations, so org_id is deliberately absent here.
    INITIAL_SCHEMA = """
        -- Main facts table
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            statement TEXT NOT NULL,
            statement_hash TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            evidence_ids_json TEXT,
            consensus_proof_id TEXT,
            source_documents_json TEXT,
            workspace_id TEXT NOT NULL,
            validation_status TEXT DEFAULT 'unverified',
            topics_json TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            superseded_by TEXT
        );

        -- Fact relations table
        CREATE TABLE IF NOT EXISTS fact_relations (
            id TEXT PRIMARY KEY,
            source_fact_id TEXT NOT NULL,
            target_fact_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            created_by TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_fact_id) REFERENCES facts(id),
            FOREIGN KEY (target_fact_id) REFERENCES facts(id)
        );

        -- Full-text search index
        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
        USING fts5(
            fact_id,
            statement,
            topics,
            content=''
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_facts_workspace ON facts(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(validation_status);
        CREATE INDEX IF NOT EXISTS idx_facts_confidence ON facts(confidence);
        CREATE INDEX IF NOT EXISTS idx_facts_hash ON facts(statement_hash);
        CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at);
        CREATE INDEX IF NOT EXISTS idx_relations_source ON fact_relations(source_fact_id);
        CREATE INDEX IF NOT EXISTS idx_relations_target ON fact_relations(target_fact_id);
        CREATE INDEX IF NOT EXISTS idx_relations_type ON fact_relations(relation_type);
    """

    DEFAULT_DB_PATH = Path(resolve_db_path("knowledge.db"))

    def __init__(self, db_path: Path | None = None):
        """Initialize the fact store.

        Args:
            db_path: Path to SQLite database (default: ARAGORA_DATA_DIR/knowledge.db)
        """
        super().__init__(db_path=db_path or self.DEFAULT_DB_PATH)

    def register_migrations(self, manager: SchemaManager) -> None:
        manager.register_migration(
            from_version=1,
            to_version=2,
            function=_add_org_scope,
            description="Add nullable facts.org_id; existing facts stay unassigned",
        )

    def _compute_statement_hash(self, statement: str) -> str:
        """Compute hash for statement deduplication."""
        normalized = " ".join(statement.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def add_fact(
        self,
        statement: str,
        workspace_id: str,
        evidence_ids: list[str] | None = None,
        source_documents: list[str] | None = None,
        confidence: float = 0.5,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        validation_status: ValidationStatus = ValidationStatus.UNVERIFIED,
        deduplicate: bool = True,
        *,
        org_id: str | None = None,
    ) -> Fact:
        """Add a fact to the store.

        Args:
            statement: The factual claim
            workspace_id: Workspace this fact belongs to
            evidence_ids: Links to evidence entries
            source_documents: Document IDs this was extracted from
            confidence: Initial confidence score
            topics: Topics for categorization
            metadata: Additional structured data
            validation_status: Initial validation status
            deduplicate: If True, return the oldest existing fact with the same
                statement, workspace and org (unassigned facts only match
                unassigned facts)
            org_id: Owning organization; None stores the fact unassigned

        Returns:
            The created or existing Fact
        """
        if org_id is not None:
            _require_org(org_id)
        evidence_ids = evidence_ids or []
        source_documents = source_documents or []
        topics = topics or []
        metadata = metadata or {}

        statement_hash = self._compute_statement_hash(statement)

        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Check for existing fact with same statement in workspace
            if deduplicate:
                cursor.execute(
                    """
                    SELECT * FROM facts
                    WHERE statement_hash = ? AND workspace_id = ? AND org_id IS ?
                    ORDER BY created_at, rowid
                    LIMIT 1
                    """,
                    (statement_hash, workspace_id, org_id),
                )
                existing = cursor.fetchone()
                if existing:
                    logger.debug("Fact deduplicated: %s", existing["id"])
                    return self._row_to_fact(existing)

            # Create new fact
            fact_id = f"fact_{uuid.uuid4().hex[:12]}"
            now = datetime.now()

            cursor.execute(
                """
                INSERT INTO facts (
                    id, statement, statement_hash, confidence,
                    evidence_ids_json, source_documents_json,
                    workspace_id, validation_status, topics_json,
                    metadata_json, created_at, updated_at, org_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    statement,
                    statement_hash,
                    confidence,
                    json.dumps(evidence_ids),
                    json.dumps(source_documents),
                    workspace_id,
                    validation_status.value,
                    json.dumps(topics),
                    json.dumps(metadata),
                    now.isoformat(),
                    now.isoformat(),
                    org_id,
                ),
            )

            # Update FTS index
            topics_str = ",".join(topics)
            cursor.execute(
                """
                INSERT INTO facts_fts (fact_id, statement, topics)
                VALUES (?, ?, ?)
                """,
                (fact_id, statement, topics_str),
            )

        return Fact(
            id=fact_id,
            statement=statement,
            confidence=confidence,
            evidence_ids=evidence_ids,
            source_documents=source_documents,
            workspace_id=workspace_id,
            validation_status=validation_status,
            topics=topics,
            metadata=metadata,
            created_at=now,
            updated_at=now,
            org_id=org_id,
        )

    def get_fact(self, fact_id: str, *, org_id: str | None = None) -> Fact | None:
        """Get a fact by ID.

        Args:
            fact_id: Fact ID
            org_id: If given, only a fact owned by this org is returned

        Returns:
            Fact or None if not found
        """
        clause, params = _org_clause(org_id)
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM facts WHERE id = ?{clause}", (fact_id, *params))  # noqa: S608 -- fixed clause, values bound
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_fact(row)

    def update_fact(
        self,
        fact_id: str,
        confidence: float | None = None,
        validation_status: ValidationStatus | None = None,
        consensus_proof_id: str | None = None,
        evidence_ids: list[str] | None = None,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        superseded_by: str | None = None,
        *,
        org_id: str | None = None,
    ) -> Fact | None:
        """Update a fact.

        Args:
            fact_id: Fact to update
            confidence: New confidence score
            validation_status: New validation status
            consensus_proof_id: Consensus proof ID
            evidence_ids: Updated evidence links
            topics: Updated topics
            metadata: Updated metadata
            superseded_by: ID of superseding fact
            org_id: If given, only a fact owned by this org is updated, and
                superseded_by must name a fact owned by the same org

        Returns:
            Updated Fact or None if not found

        Raises:
            ValueError: org_id is given and superseded_by is not a fact of that org
        """
        org_sql, org_params = _org_clause(org_id)
        if org_id is not None and superseded_by is not None:
            if self.get_fact(superseded_by, org_id=org_id) is None:
                raise ValueError("superseded_by must reference a fact in the same org")

        updates: list[str] = []
        params: list[Any] = []

        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)

        if validation_status is not None:
            updates.append("validation_status = ?")
            params.append(validation_status.value)

        if consensus_proof_id is not None:
            updates.append("consensus_proof_id = ?")
            params.append(consensus_proof_id)

        if evidence_ids is not None:
            updates.append("evidence_ids_json = ?")
            params.append(json.dumps(evidence_ids))

        if topics is not None:
            updates.append("topics_json = ?")
            params.append(json.dumps(topics))

        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata))

        if superseded_by is not None:
            updates.append("superseded_by = ?")
            params.append(superseded_by)

        if not updates:
            return self.get_fact(fact_id, org_id=org_id)

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(fact_id)
        params.extend(org_params)

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE facts SET {', '.join(updates)} WHERE id = ?{org_sql}",  # noqa: S608 -- dynamic clause from internal state
                params,
            )

            if cursor.rowcount == 0:
                return None

            # Update FTS if topics changed
            if topics is not None:
                cursor.execute(
                    "DELETE FROM facts_fts WHERE fact_id = ?",
                    (fact_id,),
                )
                # Get statement for FTS re-index
                cursor.execute("SELECT statement FROM facts WHERE id = ?", (fact_id,))
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "INSERT INTO facts_fts (fact_id, statement, topics) VALUES (?, ?, ?)",
                        (fact_id, row[0], ",".join(topics)),
                    )

        return self.get_fact(fact_id, org_id=org_id)

    def query_facts(
        self,
        query: str,
        filters: FactFilters | None = None,
    ) -> list[Fact]:
        """Search facts using full-text search.

        Args:
            query: Search query
            filters: Optional filters to apply

        Returns:
            List of matching facts
        """
        filters = filters or FactFilters()
        sanitized = sanitize_fts_query(query)

        if not sanitized:
            return self.list_facts(filters)

        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            sql = """
                SELECT f.*, bm25(facts_fts) as fts_rank
                FROM facts_fts
                JOIN facts f ON facts_fts.fact_id = f.id
                WHERE facts_fts MATCH ?
            """
            params: list[Any] = [sanitized]

            org_sql, org_params = _org_clause(filters.org_id, "f.org_id")
            sql += org_sql
            params.extend(org_params)

            # Apply filters
            if filters.workspace_id:
                sql += " AND f.workspace_id = ?"
                params.append(filters.workspace_id)

            if filters.min_confidence > 0:
                sql += " AND f.confidence >= ?"
                params.append(filters.min_confidence)

            if filters.validation_status:
                sql += " AND f.validation_status = ?"
                params.append(filters.validation_status.value)

            if not filters.include_superseded:
                sql += " AND f.superseded_by IS NULL"

            if filters.source_documents:
                # JSON array containment check
                for doc_id in filters.source_documents:
                    sql += " AND f.source_documents_json LIKE ?"
                    params.append(f'%"{doc_id}"%')

            if filters.created_after:
                sql += " AND f.created_at >= ?"
                params.append(filters.created_after.isoformat())

            if filters.created_before:
                sql += " AND f.created_at <= ?"
                params.append(filters.created_before.isoformat())

            sql += " ORDER BY fts_rank"
            sql += " LIMIT ? OFFSET ?"
            params.extend([filters.limit, filters.offset])

            cursor.execute(sql, params)
            return [self._row_to_fact(row) for row in cursor.fetchall()]

    def list_facts(self, filters: FactFilters | None = None) -> list[Fact]:
        """List facts with optional filtering.

        Args:
            filters: Optional filters

        Returns:
            List of facts
        """
        filters = filters or FactFilters()

        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            org_sql, org_params = _org_clause(filters.org_id)
            sql = f"SELECT * FROM facts WHERE 1=1{org_sql}"  # noqa: S608 -- fixed clause, values bound
            params: list[Any] = list(org_params)

            if filters.workspace_id:
                sql += " AND workspace_id = ?"
                params.append(filters.workspace_id)

            if filters.min_confidence > 0:
                sql += " AND confidence >= ?"
                params.append(filters.min_confidence)

            if filters.validation_status:
                sql += " AND validation_status = ?"
                params.append(filters.validation_status.value)

            if not filters.include_superseded:
                sql += " AND superseded_by IS NULL"

            if filters.topics:
                for topic in filters.topics:
                    sql += " AND topics_json LIKE ?"
                    params.append(f'%"{topic}"%')

            if filters.source_documents:
                for doc_id in filters.source_documents:
                    sql += " AND source_documents_json LIKE ?"
                    params.append(f'%"{doc_id}"%')

            if filters.created_after:
                sql += " AND created_at >= ?"
                params.append(filters.created_after.isoformat())

            if filters.created_before:
                sql += " AND created_at <= ?"
                params.append(filters.created_before.isoformat())

            sql += " ORDER BY confidence DESC, created_at DESC"
            sql += " LIMIT ? OFFSET ?"
            params.extend([filters.limit, filters.offset])

            cursor.execute(sql, params)
            return [self._row_to_fact(row) for row in cursor.fetchall()]

    def get_contradictions(self, fact_id: str, *, org_id: str | None = None) -> list[Fact]:
        """Get facts that contradict a given fact.

        Args:
            fact_id: Fact to find contradictions for
            org_id: If given, the fact and every returned fact must belong to this org

        Returns:
            List of contradicting facts
        """
        org_sql, org_params = _org_clause(org_id, "f.org_id")
        if org_id is not None:
            org_sql += " AND EXISTS (SELECT 1 FROM facts a WHERE a.id = ? AND a.org_id = ?)"
            org_params += (fact_id, org_id)
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get facts linked by contradiction relation
            cursor.execute(
                f"""
                SELECT f.* FROM facts f
                JOIN fact_relations r ON (
                    (r.source_fact_id = ? AND r.target_fact_id = f.id)
                    OR (r.target_fact_id = ? AND r.source_fact_id = f.id)
                )
                WHERE r.relation_type = ?
                AND f.superseded_by IS NULL{org_sql}
                """,  # noqa: S608 -- fixed clauses, values bound
                (fact_id, fact_id, FactRelationType.CONTRADICTS.value, *org_params),
            )

            return [self._row_to_fact(row) for row in cursor.fetchall()]

    @overload
    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = ...,
        created_by: str = ...,
        metadata: dict[str, Any] | None = ...,
        *,
        org_id: None = ...,
    ) -> FactRelation: ...

    @overload
    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = ...,
        created_by: str = ...,
        metadata: dict[str, Any] | None = ...,
        *,
        org_id: str,
    ) -> FactRelation | None: ...

    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = 0.5,
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
        *,
        org_id: str | None = None,
    ) -> FactRelation | None:
        """Add a relation between facts.

        Args:
            source_fact_id: Source fact ID
            target_fact_id: Target fact ID
            relation_type: Type of relation
            confidence: Confidence in relation
            created_by: Who created this relation
            metadata: Additional data
            org_id: If given, both facts must belong to this org

        Returns:
            The created relation, or None when org_id is given and either fact
            is missing or outside the org
        """
        relation_id = f"rel_{uuid.uuid4().hex[:12]}"
        now = datetime.now()
        scope_sql = ""
        scope_params: tuple[str, ...] = ()
        if org_id is not None:
            scope_sql = (
                " WHERE EXISTS (SELECT 1 FROM facts WHERE id = ? AND org_id = ?)"
                " AND EXISTS (SELECT 1 FROM facts WHERE id = ? AND org_id = ?)"
            )
            scope_params = (source_fact_id, _require_org(org_id), target_fact_id, org_id)

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                INSERT INTO fact_relations (
                    id, source_fact_id, target_fact_id, relation_type,
                    confidence, created_by, metadata_json, created_at
                ) SELECT ?, ?, ?, ?, ?, ?, ?, ?{scope_sql}
                """,  # noqa: S608 -- fixed clause, values bound
                (
                    relation_id,
                    source_fact_id,
                    target_fact_id,
                    relation_type.value,
                    confidence,
                    created_by,
                    json.dumps(metadata or {}),
                    now.isoformat(),
                    *scope_params,
                ),
            )
            if cursor.rowcount == 0:
                return None

        return FactRelation(
            id=relation_id,
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            confidence=confidence,
            created_by=created_by,
            metadata=metadata or {},
            created_at=now,
        )

    def get_relations(
        self,
        fact_id: str,
        relation_type: FactRelationType | None = None,
        as_source: bool = True,
        as_target: bool = True,
        *,
        org_id: str | None = None,
    ) -> list[FactRelation]:
        """Get relations for a fact.

        Args:
            fact_id: Fact ID
            relation_type: Optional filter by type
            as_source: Include relations where fact is source
            as_target: Include relations where fact is target
            org_id: If given, only relations whose both ends belong to this org

        Returns:
            List of relations
        """
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            conditions = []
            params: list[Any] = []

            if as_source:
                conditions.append("source_fact_id = ?")
                params.append(fact_id)
            if as_target:
                conditions.append("target_fact_id = ?")
                params.append(fact_id)

            if not conditions:
                return []

            sql = f"SELECT * FROM fact_relations r WHERE ({' OR '.join(conditions)})"  # noqa: S608 -- dynamic clause from internal state

            if relation_type:
                sql += " AND relation_type = ?"
                params.append(relation_type.value)

            if org_id is not None:
                _require_org(org_id)
                sql += (
                    " AND EXISTS (SELECT 1 FROM facts s WHERE s.id = r.source_fact_id"
                    " AND s.org_id = ?)"
                    " AND EXISTS (SELECT 1 FROM facts t WHERE t.id = r.target_fact_id"
                    " AND t.org_id = ?)"
                )
                params.extend([org_id, org_id])

            cursor.execute(sql, params)

            relations = []
            for row in cursor.fetchall():
                relations.append(
                    FactRelation(
                        id=row["id"],
                        source_fact_id=row["source_fact_id"],
                        target_fact_id=row["target_fact_id"],
                        relation_type=FactRelationType(row["relation_type"]),
                        confidence=row["confidence"],
                        created_by=row["created_by"] or "",
                        metadata=json.loads(row["metadata_json"] or "{}"),
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )
            return relations

    def delete_fact(self, fact_id: str, *, org_id: str | None = None) -> bool:
        """Delete a fact and its relations.

        Args:
            fact_id: Fact to delete
            org_id: If given, only a fact owned by this org is deleted

        Returns:
            True if deleted
        """
        org_sql, org_params = _org_clause(org_id)
        with self.connection() as conn:
            cursor = conn.cursor()

            # The fact row goes first so an org-scoped miss leaves the FTS
            # entry and relations of another org's fact untouched.
            cursor.execute(f"DELETE FROM facts WHERE id = ?{org_sql}", (fact_id, *org_params))  # noqa: S608 -- fixed clause, values bound
            deleted = cursor.rowcount > 0
            if not deleted and org_id is not None:
                return False

            cursor.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fact_id,))
            cursor.execute(
                "DELETE FROM fact_relations WHERE source_fact_id = ? OR target_fact_id = ?",
                (fact_id, fact_id),
            )

            return deleted

    def assign_org(
        self,
        org_id: str,
        *,
        workspace_id: str | None = None,
        fact_ids: list[str] | None = None,
    ) -> int:
        """Operator-only: give unassigned (NULL-org) facts an owning org.

        Facts that already belong to an org are never changed. Not exposed
        over HTTP.

        Args:
            org_id: Org to assign
            workspace_id: Only facts in this workspace
            fact_ids: Only these facts; an empty list assigns nothing

        Returns:
            Number of facts assigned
        """
        _require_org(org_id)
        sql = "UPDATE facts SET org_id = ? WHERE org_id IS NULL"
        params: list[Any] = [org_id]
        if workspace_id:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)

        with self.connection() as conn:
            cursor = conn.cursor()
            if fact_ids is None:
                cursor.execute(sql, params)
            else:
                cursor.executemany(f"{sql} AND id = ?", [(*params, fid) for fid in fact_ids])
            assigned = max(cursor.rowcount, 0)

        logger.info("Assigned %d unassigned facts to org %s", assigned, org_id)
        return assigned

    def get_statistics(
        self, workspace_id: str | None = None, *, org_id: str | None = None
    ) -> dict[str, Any]:
        """Get store statistics.

        Args:
            workspace_id: Optional workspace filter
            org_id: If given, count only this org's facts, and only relations
                whose both ends are counted facts

        Returns:
            Statistics dictionary
        """
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            conditions: list[str] = []
            params: list[Any] = []
            if workspace_id:
                conditions.append("workspace_id = ?")
                params.append(workspace_id)
            if org_id is not None:
                conditions.append("org_id = ?")
                params.append(_require_org(org_id))
            where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

            # Total facts
            cursor.execute(f"SELECT COUNT(*) as count FROM facts{where}", params)  # noqa: S608 -- internal query construction
            total = cursor.fetchone()["count"]

            # By status
            cursor.execute(
                f"""
                SELECT validation_status, COUNT(*) as count
                FROM facts{where}
                GROUP BY validation_status
                """,  # noqa: S608 -- internal query construction
                params,
            )
            by_status = {row["validation_status"]: row["count"] for row in cursor.fetchall()}

            # Average confidence
            cursor.execute(
                f"SELECT AVG(confidence) as avg FROM facts{where}",  # noqa: S608 -- internal query construction
                params,
            )
            avg_confidence = cursor.fetchone()["avg"] or 0.0

            # Verified facts
            verified_statuses = (
                ValidationStatus.MAJORITY_AGREED.value,
                ValidationStatus.BYZANTINE_AGREED.value,
                ValidationStatus.FORMALLY_PROVEN.value,
            )
            placeholders = ",".join("?" * len(verified_statuses))
            cursor.execute(
                f"""
                SELECT COUNT(*) as count FROM facts
                WHERE validation_status IN ({placeholders})
                {"".join(f" AND {c}" for c in conditions)}
                """,  # noqa: S608 -- parameterized query
                list(verified_statuses) + params,
            )
            verified = cursor.fetchone()["count"]

            # Relations count (global unless org-scoped, as before org scoping)
            if org_id is None:
                cursor.execute("SELECT COUNT(*) as count FROM fact_relations")
            else:
                end_conditions = " AND ".join(
                    f"{end}.{c}" for end in ("s", "t") for c in conditions
                )
                cursor.execute(
                    f"""
                    SELECT COUNT(*) as count FROM fact_relations r
                    JOIN facts s ON s.id = r.source_fact_id
                    JOIN facts t ON t.id = r.target_fact_id
                    WHERE {end_conditions}
                    """,  # noqa: S608 -- fixed clauses, values bound
                    params + params,
                )
            relations = cursor.fetchone()["count"]

            return {
                "total_facts": total,
                "verified_facts": verified,
                "by_status": by_status,
                "average_confidence": avg_confidence,
                "total_relations": relations,
            }

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        """Convert database row to Fact object."""
        return Fact(
            id=row["id"],
            statement=row["statement"],
            confidence=row["confidence"],
            evidence_ids=json.loads(row["evidence_ids_json"] or "[]"),
            consensus_proof_id=row["consensus_proof_id"],
            source_documents=json.loads(row["source_documents_json"] or "[]"),
            workspace_id=row["workspace_id"],
            validation_status=ValidationStatus(row["validation_status"]),
            topics=json.loads(row["topics_json"] or "[]"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            superseded_by=row["superseded_by"],
            org_id=row["org_id"],
        )


class InMemoryFactStore:
    """In-memory fact store for testing."""

    def __init__(self):
        """Initialize in-memory store."""
        self._facts: dict[str, Fact] = {}
        self._relations: dict[str, FactRelation] = {}
        # Dedup key -> id of the oldest stored fact with that key, matching
        # FactStore's ORDER BY created_at lookup.
        self._statement_hashes: dict[str, str] = {}

    def _compute_hash(self, statement: str, workspace_id: str, org_id: str | None = None) -> str:
        """Compute the deduplication key of a statement within a workspace and org."""
        normalized = " ".join(statement.lower().split())
        key = json.dumps([normalized, workspace_id, org_id])
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def _fact_hash(self, fact: Fact) -> str:
        return self._compute_hash(fact.statement, fact.workspace_id, fact.org_id)

    def _reindex_hash(self, stmt_hash: str) -> None:
        """Point a dedup key at its oldest remaining fact, or drop it."""
        matches = [f for f in self._facts.values() if self._fact_hash(f) == stmt_hash]
        if matches:
            self._statement_hashes[stmt_hash] = min(matches, key=lambda f: f.created_at).id
        else:
            self._statement_hashes.pop(stmt_hash, None)

    @staticmethod
    def _in_org(fact: Fact | None, org_id: str | None) -> bool:
        if fact is None:
            return False
        return org_id is None or fact.org_id == _require_org(org_id)

    def add_fact(
        self,
        statement: str,
        workspace_id: str,
        evidence_ids: list[str] | None = None,
        source_documents: list[str] | None = None,
        confidence: float = 0.5,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        validation_status: ValidationStatus = ValidationStatus.UNVERIFIED,
        deduplicate: bool = True,
        *,
        org_id: str | None = None,
    ) -> Fact:
        """Add a fact to memory."""
        if org_id is not None:
            _require_org(org_id)
        stmt_hash = self._compute_hash(statement, workspace_id, org_id)

        if deduplicate and stmt_hash in self._statement_hashes:
            return self._facts[self._statement_hashes[stmt_hash]]

        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        now = datetime.now()

        fact = Fact(
            id=fact_id,
            statement=statement,
            confidence=confidence,
            evidence_ids=evidence_ids or [],
            source_documents=source_documents or [],
            workspace_id=workspace_id,
            validation_status=validation_status,
            topics=topics or [],
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
            org_id=org_id,
        )

        self._facts[fact_id] = fact
        self._statement_hashes.setdefault(stmt_hash, fact_id)

        return fact

    def get_fact(self, fact_id: str, *, org_id: str | None = None) -> Fact | None:
        """Get fact by ID."""
        fact = self._facts.get(fact_id)
        return fact if self._in_org(fact, org_id) else None

    def update_fact(
        self,
        fact_id: str,
        confidence: float | None = None,
        validation_status: ValidationStatus | None = None,
        consensus_proof_id: str | None = None,
        evidence_ids: list[str] | None = None,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        superseded_by: str | None = None,
        *,
        org_id: str | None = None,
    ) -> Fact | None:
        """Update a fact."""
        if org_id is not None and superseded_by is not None:
            if self.get_fact(superseded_by, org_id=org_id) is None:
                raise ValueError("superseded_by must reference a fact in the same org")
        fact = self.get_fact(fact_id, org_id=org_id)
        if not fact:
            return None

        if confidence is not None:
            fact.confidence = confidence
        if validation_status is not None:
            fact.validation_status = validation_status
        if consensus_proof_id is not None:
            fact.consensus_proof_id = consensus_proof_id
        if evidence_ids is not None:
            fact.evidence_ids = evidence_ids
        if topics is not None:
            fact.topics = topics
        if metadata is not None:
            fact.metadata = metadata
        if superseded_by is not None:
            fact.superseded_by = superseded_by

        fact.updated_at = datetime.now()
        return fact

    def query_facts(
        self,
        query: str,
        filters: FactFilters | None = None,
    ) -> list[Fact]:
        """Search facts by keyword."""
        filters = filters or FactFilters()
        query_lower = query.lower()

        results = []
        for fact in self._facts.values():
            if not self._in_org(fact, filters.org_id):
                continue
            if filters.workspace_id and fact.workspace_id != filters.workspace_id:
                continue
            if fact.confidence < filters.min_confidence:
                continue
            if filters.validation_status and fact.validation_status != filters.validation_status:
                continue
            if not filters.include_superseded and fact.superseded_by:
                continue

            # Keyword match
            if query_lower in fact.statement.lower():
                results.append(fact)
            elif any(query_lower in t.lower() for t in fact.topics):
                results.append(fact)

        results.sort(key=lambda f: f.confidence, reverse=True)
        return results[filters.offset : filters.offset + filters.limit]

    def list_facts(self, filters: FactFilters | None = None) -> list[Fact]:
        """List facts."""
        filters = filters or FactFilters()

        results = []
        for fact in self._facts.values():
            if not self._in_org(fact, filters.org_id):
                continue
            if filters.workspace_id and fact.workspace_id != filters.workspace_id:
                continue
            if fact.confidence < filters.min_confidence:
                continue
            if filters.validation_status and fact.validation_status != filters.validation_status:
                continue
            if not filters.include_superseded and fact.superseded_by:
                continue

            results.append(fact)

        results.sort(key=lambda f: (f.confidence, f.created_at), reverse=True)
        return results[filters.offset : filters.offset + filters.limit]

    def get_contradictions(self, fact_id: str, *, org_id: str | None = None) -> list[Fact]:
        """Get contradicting facts."""
        if org_id is not None and self.get_fact(fact_id, org_id=org_id) is None:
            return []
        contradictions = []
        for rel in self._relations.values():
            if rel.relation_type != FactRelationType.CONTRADICTS:
                continue
            if rel.source_fact_id == fact_id:
                target = self.get_fact(rel.target_fact_id, org_id=org_id)
                if target and not target.superseded_by:
                    contradictions.append(target)
            elif rel.target_fact_id == fact_id:
                source = self.get_fact(rel.source_fact_id, org_id=org_id)
                if source and not source.superseded_by:
                    contradictions.append(source)
        return contradictions

    @overload
    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = ...,
        created_by: str = ...,
        metadata: dict[str, Any] | None = ...,
        *,
        org_id: None = ...,
    ) -> FactRelation: ...

    @overload
    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = ...,
        created_by: str = ...,
        metadata: dict[str, Any] | None = ...,
        *,
        org_id: str,
    ) -> FactRelation | None: ...

    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = 0.5,
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
        *,
        org_id: str | None = None,
    ) -> FactRelation | None:
        """Add a relation; with org_id, both facts must belong to that org."""
        if org_id is not None and (
            self.get_fact(source_fact_id, org_id=org_id) is None
            or self.get_fact(target_fact_id, org_id=org_id) is None
        ):
            return None
        relation_id = f"rel_{uuid.uuid4().hex[:12]}"
        relation = FactRelation(
            id=relation_id,
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            confidence=confidence,
            created_by=created_by,
            metadata=metadata or {},
            created_at=datetime.now(),
        )
        self._relations[relation_id] = relation
        return relation

    def get_relations(
        self,
        fact_id: str,
        relation_type: FactRelationType | None = None,
        as_source: bool = True,
        as_target: bool = True,
        *,
        org_id: str | None = None,
    ) -> list[FactRelation]:
        """Get relations for a fact; with org_id, only those with both ends in that org."""
        results = []
        for rel in self._relations.values():
            if relation_type and rel.relation_type != relation_type:
                continue
            if org_id is not None and not (
                self._in_org(self._facts.get(rel.source_fact_id), org_id)
                and self._in_org(self._facts.get(rel.target_fact_id), org_id)
            ):
                continue
            if as_source and rel.source_fact_id == fact_id:
                results.append(rel)
            elif as_target and rel.target_fact_id == fact_id:
                results.append(rel)
        return results

    def delete_fact(self, fact_id: str, *, org_id: str | None = None) -> bool:
        """Delete a fact."""
        if self.get_fact(fact_id, org_id=org_id) is None:
            return False

        fact = self._facts.pop(fact_id)

        # Remove from hash index, falling back to the oldest surviving duplicate
        stmt_hash = self._fact_hash(fact)
        if self._statement_hashes.get(stmt_hash) == fact_id:
            self._reindex_hash(stmt_hash)

        # Remove relations
        to_remove = [
            rid
            for rid, rel in self._relations.items()
            if rel.source_fact_id == fact_id or rel.target_fact_id == fact_id
        ]
        for rid in to_remove:
            del self._relations[rid]

        return True

    def assign_org(
        self,
        org_id: str,
        *,
        workspace_id: str | None = None,
        fact_ids: list[str] | None = None,
    ) -> int:
        """Operator-only: give unassigned facts an owning org (see FactStore.assign_org)."""
        _require_org(org_id)
        wanted = None if fact_ids is None else set(fact_ids)
        touched: set[str] = set()
        assigned = 0
        for fact in self._facts.values():
            if fact.org_id is not None:
                continue
            if workspace_id and fact.workspace_id != workspace_id:
                continue
            if wanted is not None and fact.id not in wanted:
                continue
            touched.add(self._fact_hash(fact))
            fact.org_id = org_id
            touched.add(self._fact_hash(fact))
            assigned += 1
        for stmt_hash in touched:
            self._reindex_hash(stmt_hash)
        return assigned

    def get_statistics(
        self, workspace_id: str | None = None, *, org_id: str | None = None
    ) -> dict[str, Any]:
        """Get statistics."""
        facts = [f for f in self._facts.values() if self._in_org(f, org_id)]
        if workspace_id:
            facts = [f for f in facts if f.workspace_id == workspace_id]
        if org_id is None:
            relations = len(self._relations)
        else:
            counted = {f.id for f in facts}
            relations = sum(
                1
                for r in self._relations.values()
                if r.source_fact_id in counted and r.target_fact_id in counted
            )

        by_status: dict[str, int] = {}
        total_confidence = 0.0
        verified = 0

        for fact in facts:
            status = fact.validation_status.value
            by_status[status] = by_status.get(status, 0) + 1
            total_confidence += fact.confidence
            if fact.is_verified:
                verified += 1

        return {
            "total_facts": len(facts),
            "verified_facts": verified,
            "by_status": by_status,
            "average_confidence": total_confidence / len(facts) if facts else 0.0,
            "total_relations": relations,
        }

    def close(self) -> None:
        """No-op for in-memory store."""
        pass


class ScopedFactStore:
    """A fact store view confined to one organization.

    Every read, write, deduplication lookup, relation and statistics call is
    limited to facts owned by ``org_id``, so unassigned (NULL-org) and
    other-org facts are never returned, matched or confirmed. Build it from
    the caller's authenticated org, never from request input. Methods keep the
    store's names and signatures; an ``org_id`` argument or filter naming a
    different org raises ValueError. There is deliberately no ``assign_org``.
    """

    def __init__(self, store: FactStore | InMemoryFactStore, org_id: str) -> None:
        self._store = store
        self.org_id = _require_org(org_id)

    def _org(self, org_id: str | None) -> str:
        if org_id is not None and org_id != self.org_id:
            raise ValueError("org_id does not match the scoped org")
        return self.org_id

    def _filters(self, filters: FactFilters | None) -> FactFilters:
        filters = filters or FactFilters()
        return replace(filters, org_id=self._org(filters.org_id))

    def add_fact(
        self,
        statement: str,
        workspace_id: str,
        evidence_ids: list[str] | None = None,
        source_documents: list[str] | None = None,
        confidence: float = 0.5,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        validation_status: ValidationStatus = ValidationStatus.UNVERIFIED,
        deduplicate: bool = True,
        *,
        org_id: str | None = None,
    ) -> Fact:
        return self._store.add_fact(
            statement,
            workspace_id,
            evidence_ids,
            source_documents,
            confidence,
            topics,
            metadata,
            validation_status,
            deduplicate,
            org_id=self._org(org_id),
        )

    def get_fact(self, fact_id: str, *, org_id: str | None = None) -> Fact | None:
        return self._store.get_fact(fact_id, org_id=self._org(org_id))

    def update_fact(
        self,
        fact_id: str,
        confidence: float | None = None,
        validation_status: ValidationStatus | None = None,
        consensus_proof_id: str | None = None,
        evidence_ids: list[str] | None = None,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        superseded_by: str | None = None,
        *,
        org_id: str | None = None,
    ) -> Fact | None:
        return self._store.update_fact(
            fact_id,
            confidence,
            validation_status,
            consensus_proof_id,
            evidence_ids,
            topics,
            metadata,
            superseded_by,
            org_id=self._org(org_id),
        )

    def query_facts(self, query: str, filters: FactFilters | None = None) -> list[Fact]:
        return self._store.query_facts(query, self._filters(filters))

    def list_facts(self, filters: FactFilters | None = None) -> list[Fact]:
        return self._store.list_facts(self._filters(filters))

    def get_contradictions(self, fact_id: str, *, org_id: str | None = None) -> list[Fact]:
        return self._store.get_contradictions(fact_id, org_id=self._org(org_id))

    def add_relation(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: FactRelationType,
        confidence: float = 0.5,
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
        *,
        org_id: str | None = None,
    ) -> FactRelation | None:
        return self._store.add_relation(
            source_fact_id,
            target_fact_id,
            relation_type,
            confidence,
            created_by,
            metadata,
            org_id=self._org(org_id),
        )

    def get_relations(
        self,
        fact_id: str,
        relation_type: FactRelationType | None = None,
        as_source: bool = True,
        as_target: bool = True,
        *,
        org_id: str | None = None,
    ) -> list[FactRelation]:
        return self._store.get_relations(
            fact_id, relation_type, as_source, as_target, org_id=self._org(org_id)
        )

    def delete_fact(self, fact_id: str, *, org_id: str | None = None) -> bool:
        return self._store.delete_fact(fact_id, org_id=self._org(org_id))

    def get_statistics(
        self, workspace_id: str | None = None, *, org_id: str | None = None
    ) -> dict[str, Any]:
        return self._store.get_statistics(workspace_id, org_id=self._org(org_id))
