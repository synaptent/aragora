"""
Provenance Store - Persistent storage for evidence provenance chains.

Stores provenance chains, records, and citations with SQLite backend.
Follows the SQLiteStore pattern for schema management and migrations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.reasoning.provenance import (
    Citation,
    CitationGraph,
    ProvenanceChain,
    ProvenanceManager,
    ProvenanceRecord,
    SourceType,
    TransformationType,
)
from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)


class ProvenanceStore(SQLiteStore):
    """
    SQLite-backed storage for provenance chains and citations.

    Stores:
    - Provenance chains (one per debate, contains linked records)
    - Individual provenance records (evidence with content hashes)
    - Citations (links between claims and evidence)

    Usage:
        store = ProvenanceStore()

        # Save a provenance manager
        manager = ProvenanceManager(debate_id="debate-123")
        manager.record_evidence("fact 1", SourceType.DOCUMENT, "doc-1")
        store.save_manager(manager)

        # Load it back
        loaded = store.load_manager("debate-123")
    """

    SCHEMA_NAME = "provenance_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Provenance chains (one per debate)
        CREATE TABLE IF NOT EXISTS provenance_chains (
            chain_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            genesis_hash TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            record_count INTEGER DEFAULT 0,
            data_json TEXT NOT NULL,
            UNIQUE(debate_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chains_debate ON provenance_chains(debate_id);
        CREATE INDEX IF NOT EXISTS idx_chains_created ON provenance_chains(created_at);

        -- Individual provenance records (for efficient queries)
        CREATE TABLE IF NOT EXISTS provenance_records (
            id TEXT PRIMARY KEY,
            chain_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content TEXT NOT NULL,
            content_type TEXT DEFAULT 'text',
            timestamp TEXT NOT NULL,
            previous_hash TEXT,
            parent_ids_json TEXT,
            transformation TEXT DEFAULT 'original',
            transformation_note TEXT,
            confidence REAL DEFAULT 1.0,
            verified INTEGER DEFAULT 0,
            verifier_id TEXT,
            metadata_json TEXT,
            FOREIGN KEY(chain_id) REFERENCES provenance_chains(chain_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_records_chain ON provenance_records(chain_id);
        CREATE INDEX IF NOT EXISTS idx_records_content_hash ON provenance_records(content_hash);
        CREATE INDEX IF NOT EXISTS idx_records_source ON provenance_records(source_type, source_id);

        -- Citations (links claims to evidence)
        CREATE TABLE IF NOT EXISTS provenance_citations (
            id TEXT PRIMARY KEY,
            chain_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            relevance REAL DEFAULT 1.0,
            support_type TEXT DEFAULT 'supports',
            citation_text TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(chain_id) REFERENCES provenance_chains(chain_id) ON DELETE CASCADE,
            FOREIGN KEY(evidence_id) REFERENCES provenance_records(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_citations_chain ON provenance_citations(chain_id);
        CREATE INDEX IF NOT EXISTS idx_citations_claim ON provenance_citations(claim_id);
        CREATE INDEX IF NOT EXISTS idx_citations_evidence ON provenance_citations(evidence_id);
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        **kwargs: Any,
    ):
        """Initialize the provenance store.

        Args:
            db_path: Path to SQLite database. Defaults to ARAGORA_DATA_DIR/provenance.db
        """
        if db_path is None:
            db_path = "provenance.db"

        super().__init__(db_path, **kwargs)
        logger.debug("ProvenanceStore initialized at %s", db_path)

    # =========================================================================
    # Chain Operations
    # =========================================================================

    def save_chain(self, chain: ProvenanceChain, debate_id: str) -> None:
        """Save a provenance chain.

        Args:
            chain: ProvenanceChain to save
            debate_id: ID of the debate this chain belongs to
        """
        now = datetime.now().isoformat()
        data_json = json.dumps(chain.to_dict())

        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO provenance_chains
                (chain_id, debate_id, genesis_hash, created_at, updated_at, record_count, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chain.chain_id,
                    debate_id,
                    chain.genesis_hash,
                    chain.created_at.isoformat(),
                    now,
                    len(chain.records),
                    data_json,
                ),
            )

            # Also save individual records for efficient queries
            for record in chain.records:
                self._save_record(conn, chain.chain_id, record)

        logger.debug("Saved chain %s for debate %s", chain.chain_id, debate_id)

    def load_chain(self, chain_id: str) -> ProvenanceChain | None:
        """Load a provenance chain by ID.

        Args:
            chain_id: Chain ID to load

        Returns:
            ProvenanceChain or None if not found
        """
        row = self.fetch_one(
            "SELECT data_json FROM provenance_chains WHERE chain_id = ?",
            (chain_id,),
        )
        if not row:
            return None

        data = json.loads(row[0])
        return ProvenanceChain.from_dict(data)

    def get_chain_by_debate(self, debate_id: str) -> ProvenanceChain | None:
        """Get provenance chain for a debate.

        Args:
            debate_id: Debate ID to look up

        Returns:
            ProvenanceChain or None if not found
        """
        row = self.fetch_one(
            "SELECT data_json FROM provenance_chains WHERE debate_id = ?",
            (debate_id,),
        )
        if not row:
            return None

        data = json.loads(row[0])
        return ProvenanceChain.from_dict(data)

    def delete_chain(self, chain_id: str) -> bool:
        """Delete a provenance chain and all its records/citations.

        Args:
            chain_id: Chain ID to delete

        Returns:
            True if chain was deleted
        """
        return self.delete_by_id("provenance_chains", "chain_id", chain_id)

    def list_chains(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List provenance chains with metadata.

        Args:
            limit: Maximum number of chains to return
            offset: Offset for pagination

        Returns:
            List of chain metadata dicts
        """
        rows = self.fetch_all(
            """
            SELECT chain_id, debate_id, genesis_hash, created_at, updated_at, record_count
            FROM provenance_chains
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [
            {
                "chain_id": row[0],
                "debate_id": row[1],
                "genesis_hash": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                "record_count": row[5],
            }
            for row in rows
        ]

    # =========================================================================
    # Record Operations
    # =========================================================================

    def _save_record(self, conn: Any, chain_id: str, record: ProvenanceRecord) -> None:
        """Save a provenance record (internal, called within transaction)."""
        conn.execute(
            """
            INSERT OR REPLACE INTO provenance_records
            (id, chain_id, content_hash, source_type, source_id, content, content_type,
             timestamp, previous_hash, parent_ids_json, transformation, transformation_note,
             confidence, verified, verifier_id, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                chain_id,
                record.content_hash,
                record.source_type.value,
                record.source_id,
                record.content,
                record.content_type,
                record.timestamp.isoformat(),
                record.previous_hash,
                json.dumps(record.parent_ids),
                record.transformation.value,
                record.transformation_note,
                record.confidence,
                1 if record.verified else 0,
                record.verifier_id,
                json.dumps(record.metadata),
            ),
        )

    def get_record(self, record_id: str) -> ProvenanceRecord | None:
        """Get a provenance record by ID.

        Args:
            record_id: Record ID to look up

        Returns:
            ProvenanceRecord or None if not found
        """
        row = self.fetch_one(
            """
            SELECT id, content_hash, source_type, source_id, content, content_type,
                   timestamp, previous_hash, parent_ids_json, transformation,
                   transformation_note, confidence, verified, verifier_id, metadata_json
            FROM provenance_records WHERE id = ?
            """,
            (record_id,),
        )
        if not row:
            return None

        return ProvenanceRecord(
            id=row[0],
            content_hash=row[1],
            source_type=SourceType(row[2]),
            source_id=row[3],
            content=row[4],
            content_type=row[5],
            timestamp=datetime.fromisoformat(row[6]),
            previous_hash=row[7],
            parent_ids=json.loads(row[8]) if row[8] else [],
            transformation=TransformationType(row[9]),
            transformation_note=row[10] or "",
            confidence=row[11],
            verified=bool(row[12]),
            verifier_id=row[13],
            metadata=json.loads(row[14]) if row[14] else {},
        )

    def get_records_by_chain(self, chain_id: str) -> list[ProvenanceRecord]:
        """Get all records for a chain.

        Args:
            chain_id: Chain ID to look up

        Returns:
            List of ProvenanceRecords in order
        """
        rows = self.fetch_all(
            """
            SELECT id, content_hash, source_type, source_id, content, content_type,
                   timestamp, previous_hash, parent_ids_json, transformation,
                   transformation_note, confidence, verified, verifier_id, metadata_json
            FROM provenance_records
            WHERE chain_id = ?
            ORDER BY timestamp ASC
            """,
            (chain_id,),
        )
        return [
            ProvenanceRecord(
                id=row[0],
                content_hash=row[1],
                source_type=SourceType(row[2]),
                source_id=row[3],
                content=row[4],
                content_type=row[5],
                timestamp=datetime.fromisoformat(row[6]),
                previous_hash=row[7],
                parent_ids=json.loads(row[8]) if row[8] else [],
                transformation=TransformationType(row[9]),
                transformation_note=row[10] or "",
                confidence=row[11],
                verified=bool(row[12]),
                verifier_id=row[13],
                metadata=json.loads(row[14]) if row[14] else {},
            )
            for row in rows
        ]

    def search_records(
        self,
        source_type: SourceType | None = None,
        source_id: str | None = None,
        verified_only: bool = False,
        limit: int = 100,
    ) -> list[ProvenanceRecord]:
        """Search for provenance records.

        Args:
            source_type: Filter by source type
            source_id: Filter by source ID
            verified_only: Only return verified records
            limit: Maximum records to return

        Returns:
            List of matching ProvenanceRecords
        """
        query = """
            SELECT id, content_hash, source_type, source_id, content, content_type,
                   timestamp, previous_hash, parent_ids_json, transformation,
                   transformation_note, confidence, verified, verifier_id, metadata_json
            FROM provenance_records
            WHERE 1=1
        """
        params: list[Any] = []

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type.value)

        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)

        if verified_only:
            query += " AND verified = 1"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [
            ProvenanceRecord(
                id=row[0],
                content_hash=row[1],
                source_type=SourceType(row[2]),
                source_id=row[3],
                content=row[4],
                content_type=row[5],
                timestamp=datetime.fromisoformat(row[6]),
                previous_hash=row[7],
                parent_ids=json.loads(row[8]) if row[8] else [],
                transformation=TransformationType(row[9]),
                transformation_note=row[10] or "",
                confidence=row[11],
                verified=bool(row[12]),
                verifier_id=row[13],
                metadata=json.loads(row[14]) if row[14] else {},
            )
            for row in rows
        ]

    # =========================================================================
    # Citation Operations
    # =========================================================================

    def save_citation(
        self,
        chain_id: str,
        citation: Citation,
    ) -> None:
        """Save a citation.

        Args:
            chain_id: Chain this citation belongs to
            citation: Citation to save
        """
        citation_id = f"{citation.claim_id}:{citation.evidence_id}"
        now = datetime.now().isoformat()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO provenance_citations
                (id, chain_id, claim_id, evidence_id, relevance, support_type,
                 citation_text, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    citation_id,
                    chain_id,
                    citation.claim_id,
                    citation.evidence_id,
                    citation.relevance,
                    citation.support_type,
                    citation.citation_text,
                    json.dumps(citation.metadata),
                    now,
                ),
            )

    def get_citations_by_claim(self, claim_id: str) -> list[Citation]:
        """Get all citations for a claim.

        Args:
            claim_id: Claim ID to look up

        Returns:
            List of Citations
        """
        rows = self.fetch_all(
            """
            SELECT claim_id, evidence_id, relevance, support_type, citation_text, metadata_json
            FROM provenance_citations
            WHERE claim_id = ?
            """,
            (claim_id,),
        )
        return [
            Citation(
                claim_id=row[0],
                evidence_id=row[1],
                relevance=row[2],
                support_type=row[3],
                citation_text=row[4] or "",
                metadata=json.loads(row[5]) if row[5] else {},
            )
            for row in rows
        ]

    def get_citations_by_evidence(self, evidence_id: str) -> list[Citation]:
        """Get all citations for an evidence record.

        Args:
            evidence_id: Evidence record ID to look up

        Returns:
            List of Citations
        """
        rows = self.fetch_all(
            """
            SELECT claim_id, evidence_id, relevance, support_type, citation_text, metadata_json
            FROM provenance_citations
            WHERE evidence_id = ?
            """,
            (evidence_id,),
        )
        return [
            Citation(
                claim_id=row[0],
                evidence_id=row[1],
                relevance=row[2],
                support_type=row[3],
                citation_text=row[4] or "",
                metadata=json.loads(row[5]) if row[5] else {},
            )
            for row in rows
        ]

    def get_citations_by_chain(self, chain_id: str) -> list[Citation]:
        """Get all citations for a chain.

        Args:
            chain_id: Chain ID to look up

        Returns:
            List of Citations
        """
        rows = self.fetch_all(
            """
            SELECT claim_id, evidence_id, relevance, support_type, citation_text, metadata_json
            FROM provenance_citations
            WHERE chain_id = ?
            """,
            (chain_id,),
        )
        return [
            Citation(
                claim_id=row[0],
                evidence_id=row[1],
                relevance=row[2],
                support_type=row[3],
                citation_text=row[4] or "",
                metadata=json.loads(row[5]) if row[5] else {},
            )
            for row in rows
        ]

    def load_citation_graph(self, chain_id: str) -> CitationGraph:
        """Load a CitationGraph for a chain.

        Args:
            chain_id: Chain ID to load citations for

        Returns:
            CitationGraph with all citations loaded
        """
        graph = CitationGraph()
        citations = self.get_citations_by_chain(chain_id)

        for citation in citations:
            graph.add_citation(
                claim_id=citation.claim_id,
                evidence_id=citation.evidence_id,
                relevance=citation.relevance,
                support_type=citation.support_type,
                citation_text=citation.citation_text,
            )

        return graph

    # =========================================================================
    # Manager Operations (High-level)
    # =========================================================================

    def save_manager(self, manager: ProvenanceManager) -> None:
        """Save a ProvenanceManager (chain + citations).

        Args:
            manager: ProvenanceManager to save
        """
        # Save the chain
        self.save_chain(manager.chain, manager.debate_id)

        # Save citations
        for citation in manager.graph.citations.values():
            self.save_citation(manager.chain.chain_id, citation)

        logger.debug(
            "Saved ProvenanceManager for debate %s (%s records, %s citations)",
            manager.debate_id,
            len(manager.chain.records),
            len(manager.graph.citations),
        )

    def load_manager(self, debate_id: str) -> ProvenanceManager | None:
        """Load a ProvenanceManager for a debate.

        Args:
            debate_id: Debate ID to load

        Returns:
            ProvenanceManager or None if not found
        """
        chain = self.get_chain_by_debate(debate_id)
        if not chain:
            return None

        manager = ProvenanceManager(debate_id=debate_id)
        manager.chain = chain
        manager.graph = self.load_citation_graph(chain.chain_id)

        # Recreate verifier with loaded data
        from aragora.reasoning.provenance import ProvenanceVerifier

        manager.verifier = ProvenanceVerifier(manager.chain, manager.graph)

        return manager

    # =========================================================================
    # Verification
    # =========================================================================

    def verify_chain_integrity(self, chain_id: str) -> tuple[bool, list[str]]:
        """Verify the integrity of a stored chain.

        Args:
            chain_id: Chain ID to verify

        Returns:
            Tuple of (is_valid, list of errors)
        """
        chain = self.load_chain(chain_id)
        if not chain:
            return False, [f"Chain {chain_id} not found"]

        return chain.verify_chain()

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get store statistics.

        Returns:
            Dict with chain_count, record_count, citation_count
        """
        return {
            "chain_count": self.count("provenance_chains"),
            "record_count": self.count("provenance_records"),
            "citation_count": self.count("provenance_citations"),
        }


__all__ = ["ProvenanceStore"]
