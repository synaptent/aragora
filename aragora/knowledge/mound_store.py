"""Knowledge Mound SQLite metadata store.

Extracted from mound_core.py to reduce file size.
Contains KnowledgeMoundMetaStore for SQLite-based storage operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.knowledge.unified.types import KnowledgeLink

from aragora.knowledge.types import ValidationStatus
from aragora.memory.tier_manager import MemoryTier
from aragora.storage.base_store import SQLiteStore
from aragora.utils.json_helpers import safe_json_loads

from .mound_types import (
    KnowledgeNode,
    KnowledgeRelationship,
    NodeType,
    ProvenanceChain,
    ProvenanceType,
    RelationshipType,
    _to_enum_value,
    _to_iso_string,
)

logger = logging.getLogger(__name__)


class KnowledgeMoundMetaStore(SQLiteStore):
    """
    SQLite store for Knowledge Mound metadata and relationships.

    Handles fast queries, relationship traversal, and metadata storage.
    Vector embeddings are stored in Weaviate for semantic search.
    """

    SCHEMA_NAME = "knowledge_mound"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Knowledge nodes (core metadata)
        CREATE TABLE IF NOT EXISTS knowledge_nodes (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            tier TEXT DEFAULT 'slow',
            surprise_score REAL DEFAULT 0.0,
            update_count INTEGER DEFAULT 1,
            consolidation_score REAL DEFAULT 0.0,
            validation_status TEXT DEFAULT 'unverified',
            consensus_proof_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT DEFAULT '{}'
        );

        -- Provenance tracking
        CREATE TABLE IF NOT EXISTS provenance (
            id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            agent_id TEXT,
            debate_id TEXT,
            document_id TEXT,
            user_id TEXT,
            transformations TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        -- Graph relationships
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            from_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            to_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            relationship_type TEXT NOT NULL,
            strength REAL DEFAULT 1.0,
            created_by TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        -- Topics for categorization
        CREATE TABLE IF NOT EXISTS node_topics (
            node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            PRIMARY KEY (node_id, topic)
        );

        -- Indexes for efficient queries
        CREATE INDEX IF NOT EXISTS idx_nodes_workspace ON knowledge_nodes(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_nodes_type ON knowledge_nodes(node_type);
        CREATE INDEX IF NOT EXISTS idx_nodes_tier ON knowledge_nodes(tier);
        CREATE INDEX IF NOT EXISTS idx_nodes_confidence ON knowledge_nodes(confidence DESC);
        CREATE INDEX IF NOT EXISTS idx_nodes_content_hash ON knowledge_nodes(content_hash);
        CREATE INDEX IF NOT EXISTS idx_nodes_validation ON knowledge_nodes(validation_status);
        CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_node_id);
        CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_node_id);
        CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);
        CREATE INDEX IF NOT EXISTS idx_provenance_node ON provenance(node_id);
        CREATE INDEX IF NOT EXISTS idx_topics_topic ON node_topics(topic);
    """

    def save_node(self, node: KnowledgeNode) -> str:
        """Save a knowledge node."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_nodes (
                    id, workspace_id, node_type, content, content_hash,
                    confidence, tier, surprise_score, update_count,
                    consolidation_score, validation_status, consensus_proof_id,
                    created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.workspace_id,
                    node.node_type,
                    node.content,
                    node.content_hash,
                    node.confidence,
                    _to_enum_value(node.tier),
                    node.surprise_score,
                    node.update_count,
                    node.consolidation_score,
                    _to_enum_value(node.validation_status),
                    node.consensus_proof_id,
                    _to_iso_string(node.created_at),
                    _to_iso_string(node.updated_at),
                    json.dumps(node.metadata),
                ),
            )

            # Save provenance
            if node.provenance:
                prov_id = f"prov_{node.id}"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO provenance (
                        id, node_id, source_type, source_id, agent_id,
                        debate_id, document_id, user_id, transformations, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prov_id,
                        node.id,
                        _to_enum_value(node.provenance.source_type),
                        node.provenance.source_id,
                        node.provenance.agent_id,
                        node.provenance.debate_id,
                        node.provenance.document_id,
                        node.provenance.user_id,
                        json.dumps(node.provenance.transformations),
                        _to_iso_string(node.provenance.created_at),
                    ),
                )

            # Save topics
            conn.execute("DELETE FROM node_topics WHERE node_id = ?", (node.id,))
            for topic in node.topics:
                conn.execute(
                    "INSERT OR IGNORE INTO node_topics (node_id, topic) VALUES (?, ?)",
                    (node.id, topic),
                )

        return node.id

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        """Get a knowledge node by ID."""
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM knowledge_nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return None

            # Get provenance
            prov_row = conn.execute(
                "SELECT * FROM provenance WHERE node_id = ?", (node_id,)
            ).fetchone()
            provenance = None
            if prov_row:
                provenance = ProvenanceChain(
                    source_type=ProvenanceType(prov_row["source_type"]),
                    source_id=prov_row["source_id"],
                    agent_id=prov_row["agent_id"],
                    debate_id=prov_row["debate_id"],
                    document_id=prov_row["document_id"],
                    user_id=prov_row["user_id"],
                    transformations=safe_json_loads(prov_row["transformations"], []),
                    created_at=datetime.fromisoformat(prov_row["created_at"]),
                )

            # Get topics
            topics = [
                r["topic"]
                for r in conn.execute(
                    "SELECT topic FROM node_topics WHERE node_id = ?", (node_id,)
                ).fetchall()
            ]

            # Get relationships
            supports = [
                r["to_node_id"]
                for r in conn.execute(
                    "SELECT to_node_id FROM relationships WHERE from_node_id = ? AND relationship_type = 'supports'",
                    (node_id,),
                ).fetchall()
            ]
            contradicts = [
                r["to_node_id"]
                for r in conn.execute(
                    "SELECT to_node_id FROM relationships WHERE from_node_id = ? AND relationship_type = 'contradicts'",
                    (node_id,),
                ).fetchall()
            ]
            derived_from = [
                r["to_node_id"]
                for r in conn.execute(
                    "SELECT to_node_id FROM relationships WHERE from_node_id = ? AND relationship_type = 'derived_from'",
                    (node_id,),
                ).fetchall()
            ]

            return KnowledgeNode(
                id=row["id"],
                node_type=row["node_type"],
                content=row["content"],
                confidence=row["confidence"],
                provenance=provenance,
                tier=MemoryTier(row["tier"]),
                workspace_id=row["workspace_id"],
                surprise_score=row["surprise_score"],
                update_count=row["update_count"],
                consolidation_score=row["consolidation_score"],
                validation_status=ValidationStatus(row["validation_status"]),
                consensus_proof_id=row["consensus_proof_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=safe_json_loads(row["metadata"], {}),
                topics=topics,
                supports=supports,
                contradicts=contradicts,
                derived_from=derived_from,
            )

    def save_relationship(self, rel: KnowledgeRelationship) -> str:
        """Save a relationship between nodes."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO relationships (
                    id, from_node_id, to_node_id, relationship_type,
                    strength, created_by, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rel.id,
                    rel.from_node_id,
                    rel.to_node_id,
                    rel.relationship_type,
                    rel.strength,
                    rel.created_by,
                    json.dumps(rel.metadata),
                    rel.created_at.isoformat(),
                ),
            )
        return rel.id

    def get_relationships(
        self,
        node_id: str,
        relationship_type: RelationshipType | None = None,
        direction: Literal["outgoing", "incoming", "both"] = "outgoing",
    ) -> list[KnowledgeRelationship]:
        """Get relationships for a node."""
        relationships = []
        with self.connection() as conn:
            if direction in ("outgoing", "both"):
                query = "SELECT * FROM relationships WHERE from_node_id = ?"
                params: list[Any] = [node_id]
                if relationship_type:
                    query += " AND relationship_type = ?"
                    params.append(relationship_type)
                for row in conn.execute(query, params).fetchall():
                    relationships.append(KnowledgeRelationship.from_dict(dict(row)))

            if direction in ("incoming", "both"):
                query = "SELECT * FROM relationships WHERE to_node_id = ?"
                params = [node_id]
                if relationship_type:
                    query += " AND relationship_type = ?"
                    params.append(relationship_type)
                for row in conn.execute(query, params).fetchall():
                    relationships.append(KnowledgeRelationship.from_dict(dict(row)))

        return relationships

    async def get_relationships_batch_async(
        self,
        node_ids: list[str],
        types: list[RelationshipType] | None = None,
    ) -> dict[str, list[KnowledgeLink]]:
        """Get relationships for multiple nodes in a single query.

        This is an optimized batch operation that fetches all relationships
        for the given node IDs in a single database query, avoiding N+1
        query patterns.

        Args:
            node_ids: List of node IDs to fetch relationships for
            types: Optional filter for specific relationship types

        Returns:
            Dictionary mapping each node_id to its list of relationships
        """
        # Import here to avoid circular import
        from aragora.knowledge.unified.types import KnowledgeLink
        from aragora.knowledge.unified.types import RelationshipType as UnifiedRelType

        if not node_ids:
            return {}

        # Initialize result dict with empty lists for all requested nodes
        result: dict[str, list[KnowledgeLink]] = {node_id: [] for node_id in node_ids}

        with self.connection() as conn:
            # Build query with IN clause for batch fetching
            # Note: Parentheses around the OR clause are crucial for correct precedence
            # when combined with AND (for type filtering)
            placeholders = ",".join("?" * len(node_ids))
            query = f"""
                SELECT * FROM relationships
                WHERE (from_node_id IN ({placeholders}) OR to_node_id IN ({placeholders}))
            """  # parameterized query
            params: list[Any] = list(node_ids) + list(node_ids)

            if types:
                type_placeholders = ",".join("?" * len(types))
                query += f" AND relationship_type IN ({type_placeholders})"
                params.extend(types)

            rows = conn.execute(query, params).fetchall()

            # Group relationships by node_id
            for row in rows:
                row_dict = dict(row)
                link = KnowledgeLink(
                    id=row_dict["id"],
                    source_id=row_dict["from_node_id"],
                    target_id=row_dict["to_node_id"],
                    relationship=UnifiedRelType(row_dict["relationship_type"]),
                    confidence=row_dict.get("strength", 1.0),
                    created_at=(
                        datetime.fromisoformat(row_dict["created_at"])
                        if isinstance(row_dict.get("created_at"), str)
                        else datetime.now()
                    ),
                    metadata=safe_json_loads(row_dict.get("metadata", "{}"), {}),
                )

                # Add to both source and target node lists if they're in our request
                if row_dict["from_node_id"] in result:
                    result[row_dict["from_node_id"]].append(link)
                if (
                    row_dict["to_node_id"] in result
                    and row_dict["to_node_id"] != row_dict["from_node_id"]
                ):
                    result[row_dict["to_node_id"]].append(link)

        return result

    def query_nodes(
        self,
        workspace_id: str | None = None,
        node_types: list[NodeType] | None = None,
        min_confidence: float = 0.0,
        tier: MemoryTier | None = None,
        validation_status: ValidationStatus | None = None,
        topics: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeNode]:
        """Query nodes with filters."""
        conditions = ["1=1"]
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if node_types:
            placeholders = ",".join("?" * len(node_types))
            conditions.append(f"node_type IN ({placeholders})")
            params.extend(node_types)
        if min_confidence > 0:
            conditions.append("confidence >= ?")
            params.append(min_confidence)
        if tier:
            conditions.append("tier = ?")
            params.append(tier.value)
        if validation_status:
            conditions.append("validation_status = ?")
            params.append(validation_status.value)

        where_clause = " AND ".join(conditions)

        # Handle topic filtering with join
        if topics:
            topic_placeholders = ",".join("?" * len(topics))
            query = f"""
                SELECT DISTINCT kn.id FROM knowledge_nodes kn
                JOIN node_topics nt ON kn.id = nt.node_id
                WHERE {where_clause} AND nt.topic IN ({topic_placeholders})
                ORDER BY kn.confidence DESC
                LIMIT ? OFFSET ?
            """  # dynamic clause from internal state
            params.extend(topics)
        else:
            query = f"""
                SELECT id FROM knowledge_nodes
                WHERE {where_clause}
                ORDER BY confidence DESC
                LIMIT ? OFFSET ?
            """  # dynamic clause from internal state

        params.extend([limit, offset])

        nodes = []
        with self.connection() as conn:
            for row in conn.execute(query, params).fetchall():
                node = self.get_node(row["id"])
                if node:
                    nodes.append(node)

        return nodes

    def find_by_content_hash(self, content_hash: str, workspace_id: str) -> KnowledgeNode | None:
        """Find node by content hash (for deduplication)."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id FROM knowledge_nodes WHERE content_hash = ? AND workspace_id = ?",
                (content_hash, workspace_id),
            ).fetchone()
            if row:
                return self.get_node(row["id"])
        return None

    def delete_node(self, node_id: str) -> bool:
        """Delete a knowledge node and its relationships."""
        with self.connection() as conn:
            # Delete relationships
            conn.execute(
                "DELETE FROM relationships WHERE from_node_id = ? OR to_node_id = ?",
                (node_id, node_id),
            )
            # Delete provenance
            conn.execute("DELETE FROM provenance WHERE node_id = ?", (node_id,))
            # Delete topics
            conn.execute("DELETE FROM node_topics WHERE node_id = ?", (node_id,))
            # Delete node
            cursor = conn.execute("DELETE FROM knowledge_nodes WHERE id = ?", (node_id,))
            return cursor.rowcount > 0

    def query_by_provenance(
        self,
        source_type: str | None = None,
        source_id: str | None = None,
        node_type: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        """Query nodes by provenance attributes."""
        conditions = ["1=1"]
        params: list[Any] = []

        if source_type:
            conditions.append("p.source_type = ?")
            params.append(source_type)
        if source_id:
            conditions.append("p.source_id = ?")
            params.append(source_id)
        if node_type:
            conditions.append("kn.node_type = ?")
            params.append(node_type)
        if workspace_id:
            conditions.append("kn.workspace_id = ?")
            params.append(workspace_id)

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT DISTINCT kn.id FROM knowledge_nodes kn
            JOIN provenance p ON kn.id = p.node_id
            WHERE {where_clause}
            ORDER BY kn.created_at DESC
            LIMIT ?
        """  # dynamic clause from internal state
        params.append(limit)

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [row["id"] for row in rows]

    def get_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get statistics about the knowledge mound."""
        with self.connection() as conn:
            where = "WHERE workspace_id = ?" if workspace_id else ""
            params = [workspace_id] if workspace_id else []

            total = conn.execute(
                f"SELECT COUNT(*) as count FROM knowledge_nodes {where}",  # internal clause
                params,  # internal query construction
            ).fetchone()["count"]

            by_type = {}
            for row in conn.execute(
                # internal query construction
                f"SELECT node_type, COUNT(*) as count FROM knowledge_nodes {where} GROUP BY node_type",
                params,
            ).fetchall():
                by_type[row["node_type"]] = row["count"]

            by_tier = {}
            for row in conn.execute(
                # internal query construction
                f"SELECT tier, COUNT(*) as count FROM knowledge_nodes {where} GROUP BY tier",
                params,
            ).fetchall():
                by_tier[row["tier"]] = row["count"]

            by_validation = {}
            for row in conn.execute(
                # internal query construction
                f"SELECT validation_status, COUNT(*) as count FROM knowledge_nodes {where} GROUP BY validation_status",
                params,
            ).fetchall():
                by_validation[row["validation_status"]] = row["count"]

            avg_confidence = (
                conn.execute(
                    # internal clause
                    f"SELECT AVG(confidence) as avg FROM knowledge_nodes {where}",
                    params,  # internal query construction
                ).fetchone()["avg"]
                or 0.0
            )

            relationship_count = conn.execute(
                "SELECT COUNT(*) as count FROM relationships"
            ).fetchone()["count"]

            return {
                "total_nodes": total,
                "by_type": by_type,
                "by_tier": by_tier,
                "by_validation_status": by_validation,
                "average_confidence": round(avg_confidence, 3),
                "total_relationships": relationship_count,
            }


__all__ = ["KnowledgeMoundMetaStore"]
