"""
Evidence Store.

Provides persistence for evidence snippets including:
- SQLite-based local storage
- Save, retrieve, and search evidence
- Debate-specific evidence tracking
- Evidence deduplication
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path

from aragora.evidence.metadata import MetadataEnricher
from aragora.evidence.quality import QualityContext, QualityScorer
from aragora.storage.base_store import SQLiteStore
from aragora.storage.fts_utils import MAX_FTS_TERMS, sanitize_fts_query

# Type checking import for KM adapter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.evidence_adapter import EvidenceAdapter

logger = logging.getLogger(__name__)


class EvidenceStore(SQLiteStore):
    """SQLite-based evidence persistence store."""

    SCHEMA_NAME = "evidence_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Main evidence table
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY,
            content_hash TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            snippet TEXT NOT NULL,
            url TEXT,
            reliability_score REAL DEFAULT 0.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata_json TEXT,
            enriched_metadata_json TEXT,
            quality_scores_json TEXT
        );

        -- Debate-evidence association table
        CREATE TABLE IF NOT EXISTS debate_evidence (
            debate_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            round_number INTEGER,
            relevance_score REAL DEFAULT 0.5,
            used_in_consensus BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (debate_id, evidence_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence(id)
        );

        -- Search index table for full-text search
        CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts
        USING fts5(
            evidence_id,
            title,
            snippet,
            topics,
            content=''
        );

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source);
        CREATE INDEX IF NOT EXISTS idx_evidence_created ON evidence(created_at);
        CREATE INDEX IF NOT EXISTS idx_debate_evidence_debate ON debate_evidence(debate_id);
    """

    DEFAULT_DB_PATH = Path(resolve_db_path("evidence.db"))

    def __init__(
        self,
        db_path: Path | None = None,
        enricher: MetadataEnricher | None = None,
        scorer: QualityScorer | None = None,
        km_adapter: EvidenceAdapter | None = None,
        km_min_reliability: float = 0.6,
    ):
        """Initialize the evidence store.

        Args:
            db_path: Path to SQLite database (default: ARAGORA_DATA_DIR/evidence.db)
            enricher: Optional metadata enricher
            scorer: Optional quality scorer
            km_adapter: Optional Knowledge Mound adapter for bidirectional sync
            km_min_reliability: Minimum reliability score for KM ingestion (default: 0.6)
        """
        self.enricher = enricher or MetadataEnricher()
        self.scorer = scorer or QualityScorer()
        self._km_adapter = km_adapter
        self._km_min_reliability = km_min_reliability

        # Initialize SQLiteStore with db_path
        super().__init__(db_path=db_path or self.DEFAULT_DB_PATH)

    def set_km_adapter(self, adapter: EvidenceAdapter) -> None:
        """Set the Knowledge Mound adapter for bidirectional sync.

        Args:
            adapter: EvidenceAdapter instance for KM integration
        """
        self._km_adapter = adapter

    def query_km_for_similar(
        self,
        content: str,
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Mound for similar evidence (reverse flow).

        This enables cross-session deduplication and context enrichment.

        Args:
            content: Content to find similar evidence for
            limit: Maximum results
            min_similarity: Minimum similarity threshold

        Returns:
            List of similar evidence from Knowledge Mound
        """
        if not self._km_adapter:
            return []

        try:
            return self._km_adapter.search_similar(
                content=content,
                limit=limit,
                min_similarity=min_similarity,
            )
        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.warning("Failed to query KM for similar evidence: %s", e)
            return []

    def query_km_for_topic(
        self,
        topic: str,
        limit: int = 10,
        min_reliability: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Mound for evidence on a topic (reverse flow).

        This enables context enrichment before debates.

        Args:
            topic: Topic to search for
            limit: Maximum results
            min_reliability: Minimum reliability threshold

        Returns:
            List of relevant evidence from Knowledge Mound
        """
        if not self._km_adapter:
            return []

        try:
            return self._km_adapter.search_by_topic(
                query=topic,
                limit=limit,
                min_reliability=min_reliability,
            )
        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.warning("Failed to query KM for topic evidence: %s", e)
            return []

    def save_evidence(
        self,
        evidence_id: str,
        source: str,
        title: str,
        snippet: str,
        url: str = "",
        reliability_score: float = 0.5,
        metadata: dict[str, Any] | None = None,
        debate_id: str | None = None,
        round_number: int | None = None,
        enrich: bool = True,
        score_quality: bool = True,
    ) -> str:
        """Save evidence to the store.

        Args:
            evidence_id: Unique evidence ID
            source: Source name (e.g., "github", "web")
            title: Evidence title
            snippet: Evidence content
            url: Source URL
            reliability_score: Base reliability score
            metadata: Additional metadata
            debate_id: Optional debate to associate with
            round_number: Optional round number
            enrich: Whether to enrich metadata
            score_quality: Whether to score quality

        Returns:
            The evidence ID (may be deduplicated)
        """
        # Compute content hash for deduplication
        content_hash = hashlib.sha256(snippet.encode()).hexdigest()[:32]

        # Check for existing evidence with same content
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM evidence WHERE content_hash = ?",
                (content_hash,),
            )
            existing = cursor.fetchone()
            if existing:
                evidence_id = existing["id"]
                logger.debug("Evidence deduplicated: %s", evidence_id)
            else:
                # Enrich metadata if requested
                enriched_metadata = None
                if enrich:
                    enriched_metadata = self.enricher.enrich(
                        content=snippet,
                        url=url,
                        source=source,
                        existing_metadata=metadata,
                    )

                # Score quality if requested
                quality_scores = None
                if score_quality:
                    quality_scores = self.scorer.score(
                        content=snippet,
                        metadata=enriched_metadata,
                        url=url,
                        source=source,
                    )

                # Insert new evidence
                cursor.execute(
                    """
                    INSERT INTO evidence (
                        id, content_hash, source, title, snippet, url,
                        reliability_score, metadata_json, enriched_metadata_json,
                        quality_scores_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        content_hash,
                        source,
                        title,
                        snippet,
                        url,
                        reliability_score,
                        json.dumps(metadata) if metadata else None,
                        json.dumps(enriched_metadata.to_dict()) if enriched_metadata else None,
                        json.dumps(quality_scores.to_dict()) if quality_scores else None,
                    ),
                )

                # Update FTS index
                topics = ",".join(enriched_metadata.topics) if enriched_metadata else ""
                cursor.execute(
                    """
                    INSERT INTO evidence_fts (evidence_id, title, snippet, topics)
                    VALUES (?, ?, ?, ?)
                    """,
                    (evidence_id, title, snippet, topics),
                )

            # Associate with debate if provided
            if debate_id:
                relevance = quality_scores.relevance_score if quality_scores else 0.5
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO debate_evidence (
                        debate_id, evidence_id, round_number, relevance_score
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (debate_id, evidence_id, round_number, relevance),
                )

        # Sync to Knowledge Mound if adapter configured and meets threshold
        if self._km_adapter and reliability_score >= self._km_min_reliability:
            try:
                from aragora.knowledge.mound.types import IngestionRequest, KnowledgeSource

                request = IngestionRequest(
                    content=snippet,
                    workspace_id=metadata.get("workspace_id", "default") if metadata else "default",
                    source_type=KnowledgeSource.EVIDENCE,
                    confidence=reliability_score,
                    debate_id=debate_id,
                    metadata={
                        "source": source,
                        "title": title,
                        "url": url,
                        "evidence_id": evidence_id,
                    },
                )
                self._km_adapter.store(
                    **self._km_adapter.from_ingestion_request(request, evidence_id=evidence_id)
                )
                logger.debug("Evidence synced to Knowledge Mound: %s", evidence_id)
            except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
                # Log but don't fail - KM sync is optional
                logger.warning("Failed to sync evidence to Knowledge Mound: %s", e)

        return evidence_id

    def save_evidence_snippet(
        self,
        snippet: Any,  # EvidenceSnippet
        debate_id: str | None = None,
        round_number: int | None = None,
    ) -> str:
        """Save an EvidenceSnippet object.

        Args:
            snippet: EvidenceSnippet object
            debate_id: Optional debate to associate with
            round_number: Optional round number

        Returns:
            The evidence ID
        """
        return self.save_evidence(
            evidence_id=snippet.id,
            source=snippet.source,
            title=snippet.title,
            snippet=snippet.snippet,
            url=snippet.url,
            reliability_score=snippet.reliability_score,
            metadata=snippet.metadata,
            debate_id=debate_id,
            round_number=round_number,
        )

    def save_evidence_pack(
        self,
        pack: Any,  # EvidencePack
        debate_id: str,
        round_number: int | None = None,
    ) -> list[str]:
        """Save all evidence from an EvidencePack.

        Args:
            pack: EvidencePack object
            debate_id: Debate ID to associate with
            round_number: Optional round number

        Returns:
            List of saved evidence IDs
        """
        saved_ids = []
        for snippet in pack.snippets:
            evidence_id = self.save_evidence_snippet(
                snippet=snippet,
                debate_id=debate_id,
                round_number=round_number,
            )
            saved_ids.append(evidence_id)
        return saved_ids

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        """Get evidence by ID.

        Args:
            evidence_id: Evidence ID

        Returns:
            Evidence data or None if not found
        """
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM evidence WHERE id = ?
                """,
                (evidence_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_dict(row)

    def get_debate_evidence(
        self,
        debate_id: str,
        round_number: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get all evidence for a debate.

        Args:
            debate_id: Debate ID
            round_number: Optional specific round

        Returns:
            List of evidence data
        """
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if round_number is not None:
                cursor.execute(
                    """
                    SELECT e.*, de.round_number, de.relevance_score as debate_relevance,
                           de.used_in_consensus
                    FROM evidence e
                    JOIN debate_evidence de ON e.id = de.evidence_id
                    WHERE de.debate_id = ? AND de.round_number = ?
                    ORDER BY de.relevance_score DESC
                    """,
                    (debate_id, round_number),
                )
            else:
                cursor.execute(
                    """
                    SELECT e.*, de.round_number, de.relevance_score as debate_relevance,
                           de.used_in_consensus
                    FROM evidence e
                    JOIN debate_evidence de ON e.id = de.evidence_id
                    WHERE de.debate_id = ?
                    ORDER BY de.round_number, de.relevance_score DESC
                    """,
                    (debate_id,),
                )

            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_evidence(
        self,
        query: str,
        limit: int = 20,
        source_filter: str | None = None,
        min_reliability: float = 0.0,
        context: QualityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Search evidence using full-text search.

        Args:
            query: Search query
            limit: Maximum results
            source_filter: Optional source filter
            min_reliability: Minimum reliability score
            context: Optional quality context for scoring

        Returns:
            List of matching evidence data
        """
        # Sanitize query to prevent FTS injection and limit complexity
        sanitized_query = sanitize_fts_query(query)
        if not sanitized_query:
            logger.debug("Empty FTS query after sanitization")
            return []

        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Use FTS for search
            base_query = """
                SELECT e.*,
                       bm25(evidence_fts) as fts_rank
                FROM evidence_fts
                JOIN evidence e ON evidence_fts.evidence_id = e.id
                WHERE evidence_fts MATCH ?
            """
            params: list[Any] = [sanitized_query]

            if source_filter:
                base_query += " AND e.source = ?"
                params.append(source_filter)

            if min_reliability > 0:
                base_query += " AND e.reliability_score >= ?"
                params.append(min_reliability)

            base_query += " ORDER BY fts_rank LIMIT ?"
            params.append(limit)

            cursor.execute(base_query, params)
            results = [self._row_to_dict(row) for row in cursor.fetchall()]

            # Re-score with quality scorer if context provided
            if context:
                for result in results:
                    scores = self.scorer.score(
                        content=result["snippet"],
                        url=result.get("url"),
                        source=result["source"],
                        context=context,
                    )
                    result["quality_scores"] = scores.to_dict()

                # Re-sort by quality
                results.sort(
                    key=lambda x: x.get("quality_scores", {}).get("overall_score", 0),
                    reverse=True,
                )

            return results

    def search_similar(
        self,
        content: str,
        limit: int = 10,
        exclude_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find similar evidence based on content.

        Uses a simple keyword-based similarity search.

        Args:
            content: Content to find similar evidence for
            limit: Maximum results
            exclude_id: Optional ID to exclude

        Returns:
            List of similar evidence data
        """
        # Extract keywords from content
        import re

        words = re.findall(r"\b\w{4,}\b", content.lower())
        # Remove common words
        stop_words = {
            "this",
            "that",
            "with",
            "from",
            "have",
            "been",
            "were",
            "they",
            "their",
            "which",
            "would",
            "could",
            "should",
        }
        keywords = [w for w in words if w not in stop_words][:MAX_FTS_TERMS]

        if not keywords:
            return []

        # Build FTS query - keywords are already alphanumeric from regex
        query = " OR ".join(keywords)

        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            base_query = """
                SELECT e.*,
                       bm25(evidence_fts) as fts_rank
                FROM evidence_fts
                JOIN evidence e ON evidence_fts.evidence_id = e.id
                WHERE evidence_fts MATCH ?
            """
            params: list[Any] = [query]

            if exclude_id:
                base_query += " AND e.id != ?"
                params.append(exclude_id)

            base_query += " ORDER BY fts_rank LIMIT ?"
            params.append(limit)

            cursor.execute(base_query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def mark_used_in_consensus(
        self,
        debate_id: str,
        evidence_ids: list[str],
    ) -> None:
        """Mark evidence as used in consensus.

        Args:
            debate_id: Debate ID
            evidence_ids: List of evidence IDs used
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                UPDATE debate_evidence
                SET used_in_consensus = TRUE
                WHERE debate_id = ? AND evidence_id = ?
                """,
                [(debate_id, eid) for eid in evidence_ids],
            )

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete evidence by ID.

        Args:
            evidence_id: Evidence ID

        Returns:
            True if deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            # Delete from FTS
            cursor.execute(
                "DELETE FROM evidence_fts WHERE evidence_id = ?",
                (evidence_id,),
            )

            # Delete associations
            cursor.execute(
                "DELETE FROM debate_evidence WHERE evidence_id = ?",
                (evidence_id,),
            )

            # Delete evidence
            cursor.execute(
                "DELETE FROM evidence WHERE id = ?",
                (evidence_id,),
            )

            return cursor.rowcount > 0

    def delete_debate_evidence(self, debate_id: str) -> int:
        """Delete all evidence associations for a debate.

        Does not delete the evidence itself, only the association.

        Args:
            debate_id: Debate ID

        Returns:
            Number of associations deleted
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM debate_evidence WHERE debate_id = ?",
                (debate_id,),
            )
            return cursor.rowcount

    def get_statistics(self) -> dict[str, Any]:
        """Get store statistics.

        Returns:
            Dictionary of statistics
        """
        with self.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Total evidence count
            cursor.execute("SELECT COUNT(*) as count FROM evidence")
            total_count = cursor.fetchone()["count"]

            # Count by source
            cursor.execute("""
                SELECT source, COUNT(*) as count
                FROM evidence
                GROUP BY source
                ORDER BY count DESC
            """)
            by_source = {row["source"]: row["count"] for row in cursor.fetchall()}

            # Average reliability
            cursor.execute("""
                SELECT AVG(reliability_score) as avg_reliability
                FROM evidence
            """)
            avg_reliability = cursor.fetchone()["avg_reliability"] or 0.0

            # Debate associations
            cursor.execute("SELECT COUNT(*) as count FROM debate_evidence")
            debate_associations = cursor.fetchone()["count"]

            # Unique debates
            cursor.execute("SELECT COUNT(DISTINCT debate_id) as count FROM debate_evidence")
            unique_debates = cursor.fetchone()["count"]

            return {
                "total_evidence": total_count,
                "by_source": by_source,
                "average_reliability": avg_reliability,
                "debate_associations": debate_associations,
                "unique_debates": unique_debates,
            }

    def cleanup_expired_evidence(
        self,
        retention_days: int = 90,
        batch_size: int = 1000,
        preserve_high_reliability: bool = True,
        reliability_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """Clean up expired evidence based on retention policy.

        Removes evidence older than retention_days that is not linked to
        any active debates and optionally preserves high-reliability evidence.

        Args:
            retention_days: Number of days to retain evidence (default: 90)
            batch_size: Maximum records to delete per batch (default: 1000)
            preserve_high_reliability: Keep high-reliability evidence (default: True)
            reliability_threshold: Reliability score threshold (default: 0.8)

        Returns:
            Dictionary with cleanup statistics:
            - deleted_count: Number of evidence records deleted
            - preserved_count: Number preserved due to reliability
            - linked_count: Number preserved due to debate links
            - duration_ms: Cleanup duration in milliseconds
        """
        import time

        # SECURITY: Validate retention_days to prevent SQL injection
        if not isinstance(retention_days, int) or retention_days < 0 or retention_days > 36500:
            raise ValueError(
                f"retention_days must be an integer between 0 and 36500, got: {retention_days!r}"
            )

        start_time = time.time()

        with self.connection() as conn:
            cursor = conn.cursor()

            # Calculate cutoff date (safe after validation)
            cutoff_query = f"datetime('now', '-{retention_days} days')"

            # Find expired evidence not linked to any debate
            # Optionally preserve high-reliability evidence
            if preserve_high_reliability:
                find_expired_query = f"""
                    SELECT e.id FROM evidence e
                    WHERE e.created_at < {cutoff_query}
                    AND e.reliability_score < ?
                    AND NOT EXISTS (
                        SELECT 1 FROM debate_evidence de WHERE de.evidence_id = e.id
                    )
                    LIMIT ?
                """  # noqa: S608 -- internal query construction
                cursor.execute(find_expired_query, (reliability_threshold, batch_size))
            else:
                find_expired_query = f"""
                    SELECT e.id FROM evidence e
                    WHERE e.created_at < {cutoff_query}
                    AND NOT EXISTS (
                        SELECT 1 FROM debate_evidence de WHERE de.evidence_id = e.id
                    )
                    LIMIT ?
                """  # noqa: S608 -- internal query construction
                cursor.execute(find_expired_query, (batch_size,))

            expired_ids = [row[0] for row in cursor.fetchall()]

            if not expired_ids:
                return {
                    "deleted_count": 0,
                    "preserved_count": 0,
                    "linked_count": 0,
                    "duration_ms": (time.time() - start_time) * 1000,
                }

            # Delete from FTS index first
            placeholders = ",".join("?" * len(expired_ids))
            cursor.execute(
                f"DELETE FROM evidence_fts WHERE evidence_id IN ({placeholders})",  # noqa: S608 -- parameterized query
                expired_ids,
            )

            # Delete the evidence records
            cursor.execute(
                f"DELETE FROM evidence WHERE id IN ({placeholders})",  # noqa: S608 -- parameterized query
                expired_ids,
            )
            deleted_count = cursor.rowcount

            # Count preserved due to high reliability
            if preserve_high_reliability:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM evidence
                    WHERE created_at < {cutoff_query}
                    AND reliability_score >= ?
                """,  # noqa: S608 -- internal query construction
                    (reliability_threshold,),
                )
                preserved_count = cursor.fetchone()[0]
            else:
                preserved_count = 0

            # Count linked (preserved due to debate association)
            cursor.execute(f"""
                SELECT COUNT(DISTINCT e.id) FROM evidence e
                INNER JOIN debate_evidence de ON de.evidence_id = e.id
                WHERE e.created_at < {cutoff_query}
            """)  # noqa: S608 -- internal query construction
            linked_count = cursor.fetchone()[0]

            conn.commit()

            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "Evidence cleanup: deleted=%s, "
                "preserved_high_reliability=%s, "
                "preserved_linked=%s, duration=%.1fms",
                deleted_count,
                preserved_count,
                linked_count,
                duration_ms,
            )

            return {
                "deleted_count": deleted_count,
                "preserved_count": preserved_count,
                "linked_count": linked_count,
                "duration_ms": duration_ms,
            }

    def get_retention_statistics(self, retention_days: int = 90) -> dict[str, Any]:
        """Get statistics about evidence that would be affected by retention policy.

        Args:
            retention_days: Retention period to analyze

        Returns:
            Dictionary with retention statistics

        Raises:
            ValueError: If retention_days is not a valid positive integer
        """
        # Validate and sanitize retention_days to prevent SQL injection
        # SQLite datetime() modifiers don't support parameterization
        try:
            retention_days = int(retention_days)
            if retention_days < 0:
                raise ValueError("retention_days must be non-negative")
            if retention_days > 36500:  # Max ~100 years
                raise ValueError("retention_days exceeds maximum allowed value")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid retention_days: {e}") from e

        with self.connection() as conn:
            cursor = conn.cursor()
            # Pre-compute cutoff date in Python to avoid SQL interpolation
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            cutoff_iso = cutoff_date.isoformat()

            # Total expired
            cursor.execute(
                "SELECT COUNT(*) FROM evidence WHERE created_at < ?",
                (cutoff_iso,),
            )
            total_expired = cursor.fetchone()[0]

            # Expired but linked
            cursor.execute(
                """
                SELECT COUNT(DISTINCT e.id) FROM evidence e
                INNER JOIN debate_evidence de ON de.evidence_id = e.id
                WHERE e.created_at < ?
                """,
                (cutoff_iso,),
            )
            expired_linked = cursor.fetchone()[0]

            # Expired with high reliability
            cursor.execute(
                """
                SELECT COUNT(*) FROM evidence
                WHERE created_at < ?
                AND reliability_score >= 0.8
                """,
                (cutoff_iso,),
            )
            expired_high_reliability = cursor.fetchone()[0]

            # Deletable (expired, not linked, low reliability)
            cursor.execute(
                """
                SELECT COUNT(*) FROM evidence e
                WHERE e.created_at < ?
                AND e.reliability_score < 0.8
                AND NOT EXISTS (
                    SELECT 1 FROM debate_evidence de WHERE de.evidence_id = e.id
                )
                """,
                (cutoff_iso,),
            )
            deletable = cursor.fetchone()[0]

            return {
                "retention_days": retention_days,
                "total_expired": total_expired,
                "expired_linked": expired_linked,
                "expired_high_reliability": expired_high_reliability,
                "deletable": deletable,
            }

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to dictionary."""
        data = dict(row)

        # Parse JSON fields
        if data.get("metadata_json"):
            data["metadata"] = json.loads(data["metadata_json"])
            del data["metadata_json"]
        else:
            data["metadata"] = {}

        if data.get("enriched_metadata_json"):
            data["enriched_metadata"] = json.loads(data["enriched_metadata_json"])
            del data["enriched_metadata_json"]

        if data.get("quality_scores_json"):
            data["quality_scores"] = json.loads(data["quality_scores_json"])
            del data["quality_scores_json"]

        return data

    def close(self) -> None:
        """Close database connections.

        Closes the underlying database manager connections.
        """
        if hasattr(self, "_manager") and self._manager:
            self._manager.close()


class InMemoryEvidenceStore:
    """In-memory evidence store for testing and ephemeral use."""

    def __init__(
        self,
        enricher: MetadataEnricher | None = None,
        scorer: QualityScorer | None = None,
    ):
        """Initialize in-memory store."""
        self.enricher = enricher or MetadataEnricher()
        self.scorer = scorer or QualityScorer()
        self._evidence: dict[str, dict[str, Any]] = {}
        self._debate_evidence: dict[str, dict[str, dict[str, Any]]] = {}
        self._content_hashes: dict[str, str] = {}  # hash -> evidence_id

    def save_evidence(
        self,
        evidence_id: str,
        source: str,
        title: str,
        snippet: str,
        url: str = "",
        reliability_score: float = 0.5,
        metadata: dict[str, Any] | None = None,
        debate_id: str | None = None,
        round_number: int | None = None,
        enrich: bool = True,
        score_quality: bool = True,
    ) -> str:
        """Save evidence to memory."""
        content_hash = hashlib.sha256(snippet.encode()).hexdigest()[:32]

        # Check for deduplication
        if content_hash in self._content_hashes:
            evidence_id = self._content_hashes[content_hash]
        else:
            enriched_metadata = None
            if enrich:
                enriched_metadata = self.enricher.enrich(
                    content=snippet,
                    url=url,
                    source=source,
                    existing_metadata=metadata,
                )

            quality_scores = None
            if score_quality:
                quality_scores = self.scorer.score(
                    content=snippet,
                    metadata=enriched_metadata,
                    url=url,
                    source=source,
                )

            self._evidence[evidence_id] = {
                "id": evidence_id,
                "content_hash": content_hash,
                "source": source,
                "title": title,
                "snippet": snippet,
                "url": url,
                "reliability_score": reliability_score,
                "metadata": metadata or {},
                "enriched_metadata": enriched_metadata.to_dict() if enriched_metadata else None,
                "quality_scores": quality_scores.to_dict() if quality_scores else None,
                "created_at": datetime.now().isoformat(),
            }
            self._content_hashes[content_hash] = evidence_id

        # Associate with debate
        if debate_id:
            if debate_id not in self._debate_evidence:
                self._debate_evidence[debate_id] = {}
            self._debate_evidence[debate_id][evidence_id] = {
                "round_number": round_number,
                "relevance_score": 0.5,
                "used_in_consensus": False,
            }

        return evidence_id

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        """Get evidence by ID."""
        return self._evidence.get(evidence_id)

    def get_debate_evidence(
        self,
        debate_id: str,
        round_number: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get evidence for a debate."""
        if debate_id not in self._debate_evidence:
            return []

        results = []
        for eid, assoc in self._debate_evidence[debate_id].items():
            if round_number is not None and assoc.get("round_number") != round_number:
                continue
            evidence = self._evidence.get(eid)
            if evidence:
                result = {**evidence, **assoc}
                results.append(result)

        return sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True)

    def search_evidence(
        self,
        query: str,
        limit: int = 20,
        source_filter: str | None = None,
        min_reliability: float = 0.0,
        context: QualityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Search evidence by keyword."""
        query_lower = query.lower()
        results = []

        for evidence in self._evidence.values():
            if source_filter and evidence["source"] != source_filter:
                continue
            if evidence["reliability_score"] < min_reliability:
                continue

            # Simple keyword matching
            text = f"{evidence['title']} {evidence['snippet']}".lower()
            if query_lower in text:
                results.append(evidence)

        # Sort by reliability and limit
        results.sort(key=lambda x: x["reliability_score"], reverse=True)
        return results[:limit]

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete evidence."""
        if evidence_id in self._evidence:
            # Remove content hash mapping
            content_hash = self._evidence[evidence_id].get("content_hash")
            if content_hash in self._content_hashes:
                del self._content_hashes[content_hash]

            del self._evidence[evidence_id]

            # Remove debate associations
            for debate_id in list(self._debate_evidence.keys()):
                if evidence_id in self._debate_evidence[debate_id]:
                    del self._debate_evidence[debate_id][evidence_id]

            return True
        return False

    def get_statistics(self) -> dict[str, Any]:
        """Get store statistics."""
        by_source: dict[str, int] = {}
        total_reliability = 0.0

        for evidence in self._evidence.values():
            source = evidence["source"]
            by_source[source] = by_source.get(source, 0) + 1
            total_reliability += evidence["reliability_score"]

        return {
            "total_evidence": len(self._evidence),
            "by_source": by_source,
            "average_reliability": (
                total_reliability / len(self._evidence) if self._evidence else 0.0
            ),
            "debate_associations": sum(len(d) for d in self._debate_evidence.values()),
            "unique_debates": len(self._debate_evidence),
        }

    def close(self) -> None:
        """No-op for in-memory store."""
        pass
