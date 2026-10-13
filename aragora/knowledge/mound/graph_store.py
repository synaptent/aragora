"""
Knowledge Graph Store for persistent relationship and lineage tracking.

Provides persistent storage for:
- Knowledge relationships (supports, contradicts, elaborates, etc.)
- Belief lineage (supersession chains showing how knowledge evolved)
- Domain taxonomy (hierarchical organization of knowledge domains)

Usage:
    from aragora.knowledge.mound.graph_store import KnowledgeGraphStore

    store = KnowledgeGraphStore(db_path="path/to/graph.db")

    # Add a relationship
    link_id = await store.add_link(
        source_id="km_abc123",
        target_id="km_def456",
        relationship=RelationshipType.SUPPORTS,
        created_by="agent_claude",
    )

    # Track belief evolution
    await store.add_lineage(
        current_id="km_new123",
        predecessor_id="km_old456",
        supersession_reason="New evidence from debate",
        debate_id="debate_789",
    )

    # Get full lineage chain
    lineage = await store.get_lineage("km_new123", direction="predecessors")
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from aragora.knowledge.mound.types import RelationshipType
from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)


@dataclass
class GraphLink:
    """A relationship between two knowledge items."""

    id: str
    source_id: str
    target_id: str
    relationship: RelationshipType
    confidence: float
    created_by: str | None
    created_at: datetime
    tenant_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LineageNode:
    """A node in a belief lineage chain."""

    id: str
    current_id: str
    predecessor_id: str | None
    supersession_reason: str | None
    debate_id: str | None
    created_at: datetime
    tenant_id: str


@dataclass
class GraphTraversalResult:
    """Result of traversing the knowledge graph."""

    nodes: list[str]  # Knowledge Mound IDs
    edges: list[GraphLink]
    root_id: str
    depth: int
    total_nodes: int
    total_edges: int


class KnowledgeGraphStore(SQLiteStore):
    """
    Persistent storage for knowledge graph relationships and belief lineage.

    Features:
    - Bidirectional relationship storage
    - Belief lineage tracking (supersession chains)
    - Graph traversal queries
    - Multi-tenant isolation
    - Contradiction detection
    """

    SCHEMA_NAME = "knowledge_graph"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Knowledge relationships between items
        CREATE TABLE IF NOT EXISTS knowledge_links (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,                -- Knowledge Mound ID (km_xxx)
            target_id TEXT NOT NULL,
            relationship TEXT NOT NULL,             -- supports|contradicts|elaborates|supersedes|derived_from|related_to|cites
            confidence REAL DEFAULT 1.0,
            created_by TEXT,                        -- Agent ID or user ID
            created_at TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            metadata TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_links_source ON knowledge_links(source_id);
        CREATE INDEX IF NOT EXISTS idx_links_target ON knowledge_links(target_id);
        CREATE INDEX IF NOT EXISTS idx_links_relationship ON knowledge_links(relationship);
        CREATE INDEX IF NOT EXISTS idx_links_tenant ON knowledge_links(tenant_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_links_unique
            ON knowledge_links(source_id, target_id, relationship, tenant_id);

        -- Belief lineage tracking (supersession chains)
        CREATE TABLE IF NOT EXISTS belief_lineage (
            id TEXT PRIMARY KEY,
            current_id TEXT NOT NULL,               -- Current active belief (km_xxx)
            predecessor_id TEXT,                    -- Previous version (NULL for origins)
            supersession_reason TEXT,               -- Why it was superseded
            debate_id TEXT,                         -- Debate that caused supersession
            created_at TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default'
        );

        CREATE INDEX IF NOT EXISTS idx_lineage_current ON belief_lineage(current_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_predecessor ON belief_lineage(predecessor_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_tenant ON belief_lineage(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_debate ON belief_lineage(debate_id);

        -- Domain taxonomy for hierarchical organization
        CREATE TABLE IF NOT EXISTS domain_taxonomy (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT,                         -- NULL for root domains
            description TEXT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES domain_taxonomy(id)
        );

        CREATE INDEX IF NOT EXISTS idx_taxonomy_parent ON domain_taxonomy(parent_id);
        CREATE INDEX IF NOT EXISTS idx_taxonomy_tenant ON domain_taxonomy(tenant_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_taxonomy_unique
            ON domain_taxonomy(name, parent_id, tenant_id);

        -- Archive tables for audit trails
        CREATE TABLE IF NOT EXISTS knowledge_links_archive (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            confidence REAL,
            created_by TEXT,
            tenant_id TEXT NOT NULL,
            archived_at TEXT NOT NULL,
            archive_reason TEXT
        );
    """

    def __init__(
        self,
        db_path: str | Path,
        default_tenant_id: str = "default",
    ):
        """
        Initialize the Knowledge Graph Store.

        Args:
            db_path: Path to SQLite database
            default_tenant_id: Default tenant for operations
        """
        super().__init__(db_path)
        self._default_tenant_id = default_tenant_id
        logger.info("KnowledgeGraphStore initialized")

    # =========================================================================
    # Link Operations
    # =========================================================================

    async def add_link(
        self,
        source_id: str,
        target_id: str,
        relationship: RelationshipType | str,
        confidence: float = 1.0,
        created_by: str | None = None,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a relationship between two knowledge items.

        Args:
            source_id: Source knowledge item ID
            target_id: Target knowledge item ID
            relationship: Type of relationship
            confidence: Confidence in the relationship (0-1)
            created_by: Agent or user who created the link
            tenant_id: Tenant ID for isolation
            metadata: Additional metadata

        Returns:
            Link ID
        """
        tenant_id = tenant_id or self._default_tenant_id
        rel_str = relationship.value if isinstance(relationship, RelationshipType) else relationship

        return await asyncio.to_thread(
            self._sync_add_link,
            source_id,
            target_id,
            rel_str,
            confidence,
            created_by,
            tenant_id,
            metadata or {},
        )

    def _sync_add_link(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        confidence: float,
        created_by: str | None,
        tenant_id: str,
        metadata: dict[str, Any],
    ) -> str:
        """Synchronous link insertion."""
        import json

        link_id = f"link_{uuid.uuid4().hex[:12]}"

        with self.connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO knowledge_links
                    (id, source_id, target_id, relationship, confidence,
                     created_by, created_at, tenant_id, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        link_id,
                        source_id,
                        target_id,
                        relationship,
                        confidence,
                        created_by,
                        datetime.now().isoformat(),
                        tenant_id,
                        json.dumps(metadata),
                    ),
                )
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as e:
                if "UNIQUE constraint" in str(e):
                    # Link already exists, return existing ID
                    row = self.fetch_one(
                        """
                        SELECT id FROM knowledge_links
                        WHERE source_id = ? AND target_id = ?
                        AND relationship = ? AND tenant_id = ?
                        """,
                        (source_id, target_id, relationship, tenant_id),
                    )
                    return row[0] if row else link_id
                raise

        logger.debug("Added link: %s --%s--> %s", source_id, relationship, target_id)
        return link_id

    async def get_links(
        self,
        node_id: str,
        relationship_types: list[RelationshipType] | None = None,
        direction: Literal["outgoing", "incoming", "both"] = "both",
        tenant_id: str | None = None,
    ) -> list[GraphLink]:
        """
        Get relationships for a knowledge item.

        Args:
            node_id: Knowledge item ID
            relationship_types: Filter by relationship types
            direction: Direction of relationships to fetch
            tenant_id: Tenant ID

        Returns:
            List of graph links
        """
        tenant_id = tenant_id or self._default_tenant_id
        type_strs = [r.value for r in relationship_types] if relationship_types else None

        return await asyncio.to_thread(
            self._sync_get_links, node_id, type_strs, direction, tenant_id
        )

    def _sync_get_links(
        self,
        node_id: str,
        relationship_types: list[str] | None,
        direction: str,
        tenant_id: str,
    ) -> list[GraphLink]:
        """Synchronous link retrieval."""
        import json

        results = []

        # Build queries based on direction
        queries = []
        if direction in ("outgoing", "both"):
            queries.append(("source_id", node_id))
        if direction in ("incoming", "both"):
            queries.append(("target_id", node_id))

        for column, value in queries:
            sql = f"""
                SELECT id, source_id, target_id, relationship, confidence,
                       created_by, created_at, tenant_id, metadata
                FROM knowledge_links
                WHERE {column} = ? AND tenant_id = ?
            """  # column name interpolation, parameterized
            params: list = [value, tenant_id]

            if relationship_types:
                placeholders = ",".join("?" * len(relationship_types))
                sql += f" AND relationship IN ({placeholders})"
                params.extend(relationship_types)

            rows = self.fetch_all(sql, tuple(params))

            for row in rows:
                results.append(
                    GraphLink(
                        id=row[0],
                        source_id=row[1],
                        target_id=row[2],
                        relationship=RelationshipType(row[3]),
                        confidence=row[4],
                        created_by=row[5],
                        created_at=datetime.fromisoformat(row[6]),
                        tenant_id=row[7],
                        metadata=json.loads(row[8]) if row[8] else {},
                    )
                )

        # Deduplicate if direction is "both"
        seen_ids = set()
        unique_results = []
        for link in results:
            if link.id not in seen_ids:
                seen_ids.add(link.id)
                unique_results.append(link)

        return unique_results

    async def delete_link(
        self,
        link_id: str,
        archive: bool = True,
        reason: str = "manual",
    ) -> bool:
        """Delete a relationship."""
        return await asyncio.to_thread(self._sync_delete_link, link_id, archive, reason)

    def _sync_delete_link(self, link_id: str, archive: bool, reason: str) -> bool:
        """Synchronous link deletion with optional archiving."""
        with self.connection() as conn:
            if archive:
                conn.execute(
                    """
                    INSERT INTO knowledge_links_archive
                    (id, source_id, target_id, relationship, confidence,
                     created_by, tenant_id, archived_at, archive_reason)
                    SELECT id, source_id, target_id, relationship, confidence,
                           created_by, tenant_id, ?, ?
                    FROM knowledge_links WHERE id = ?
                    """,
                    (datetime.now().isoformat(), reason, link_id),
                )

            cursor = conn.execute("DELETE FROM knowledge_links WHERE id = ?", (link_id,))
            return cursor.rowcount > 0

    # =========================================================================
    # Contradiction Detection
    # =========================================================================

    async def find_contradictions(
        self,
        node_id: str,
        tenant_id: str | None = None,
    ) -> list[str]:
        """
        Find items that contradict a given knowledge item.

        Args:
            node_id: Knowledge item ID
            tenant_id: Tenant ID

        Returns:
            List of contradicting item IDs
        """
        tenant_id = tenant_id or self._default_tenant_id
        return await asyncio.to_thread(self._sync_find_contradictions, node_id, tenant_id)

    def _sync_find_contradictions(self, node_id: str, tenant_id: str) -> list[str]:
        """Synchronous contradiction lookup."""
        rows = self.fetch_all(
            """
            SELECT CASE
                WHEN source_id = ? THEN target_id
                ELSE source_id
            END as contradicting_id
            FROM knowledge_links
            WHERE (source_id = ? OR target_id = ?)
            AND relationship = ?
            AND tenant_id = ?
            """,
            (
                node_id,
                node_id,
                node_id,
                RelationshipType.CONTRADICTS.value,
                tenant_id,
            ),
        )
        return [row[0] for row in rows]

    # =========================================================================
    # Belief Lineage
    # =========================================================================

    async def add_lineage(
        self,
        current_id: str,
        predecessor_id: str | None = None,
        supersession_reason: str | None = None,
        debate_id: str | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """
        Track belief evolution by recording supersession.

        Args:
            current_id: Current (new) belief ID
            predecessor_id: Previous belief that was superseded (None for origins)
            supersession_reason: Why the belief evolved
            debate_id: Debate that caused the change
            tenant_id: Tenant ID

        Returns:
            Lineage entry ID
        """
        tenant_id = tenant_id or self._default_tenant_id

        return await asyncio.to_thread(
            self._sync_add_lineage,
            current_id,
            predecessor_id,
            supersession_reason,
            debate_id,
            tenant_id,
        )

    def _sync_add_lineage(
        self,
        current_id: str,
        predecessor_id: str | None,
        supersession_reason: str | None,
        debate_id: str | None,
        tenant_id: str,
    ) -> str:
        """Synchronous lineage insertion."""
        lineage_id = f"lin_{uuid.uuid4().hex[:12]}"

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO belief_lineage
                (id, current_id, predecessor_id, supersession_reason,
                 debate_id, created_at, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lineage_id,
                    current_id,
                    predecessor_id,
                    supersession_reason,
                    debate_id,
                    datetime.now().isoformat(),
                    tenant_id,
                ),
            )

            # Also create a SUPERSEDES link for graph traversal
            if predecessor_id:
                link_id = f"link_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_links
                    (id, source_id, target_id, relationship, confidence,
                     created_at, tenant_id, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        link_id,
                        current_id,
                        predecessor_id,
                        RelationshipType.SUPERSEDES.value,
                        1.0,
                        datetime.now().isoformat(),
                        tenant_id,
                        "{}",
                    ),
                )

        logger.debug("Added lineage: %s supersedes %s", current_id, predecessor_id)
        return lineage_id

    async def get_lineage(
        self,
        item_id: str,
        direction: Literal["predecessors", "successors", "both"] = "both",
        tenant_id: str | None = None,
    ) -> list[LineageNode]:
        """
        Get belief evolution history.

        Args:
            item_id: Knowledge item ID
            direction: Which direction to traverse
            tenant_id: Tenant ID

        Returns:
            List of lineage nodes in chronological order
        """
        tenant_id = tenant_id or self._default_tenant_id
        return await asyncio.to_thread(self._sync_get_lineage, item_id, direction, tenant_id)

    def _sync_get_lineage(
        self,
        item_id: str,
        direction: str,
        tenant_id: str,
    ) -> list[LineageNode]:
        """Synchronous lineage traversal."""
        results = []
        visited = set()

        def _traverse_predecessors(current_id: str) -> None:
            if current_id in visited:
                return
            visited.add(current_id)

            rows = self.fetch_all(
                """
                SELECT id, current_id, predecessor_id, supersession_reason,
                       debate_id, created_at, tenant_id
                FROM belief_lineage
                WHERE current_id = ? AND tenant_id = ?
                """,
                (current_id, tenant_id),
            )

            for row in rows:
                node = LineageNode(
                    id=row[0],
                    current_id=row[1],
                    predecessor_id=row[2],
                    supersession_reason=row[3],
                    debate_id=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                    tenant_id=row[6],
                )
                results.append(node)

                if node.predecessor_id:
                    _traverse_predecessors(node.predecessor_id)

        def _traverse_successors(current_id: str) -> None:
            if current_id in visited:
                return
            visited.add(current_id)

            rows = self.fetch_all(
                """
                SELECT id, current_id, predecessor_id, supersession_reason,
                       debate_id, created_at, tenant_id
                FROM belief_lineage
                WHERE predecessor_id = ? AND tenant_id = ?
                """,
                (current_id, tenant_id),
            )

            for row in rows:
                node = LineageNode(
                    id=row[0],
                    current_id=row[1],
                    predecessor_id=row[2],
                    supersession_reason=row[3],
                    debate_id=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                    tenant_id=row[6],
                )
                results.append(node)
                _traverse_successors(node.current_id)

        if direction in ("predecessors", "both"):
            _traverse_predecessors(item_id)

        visited.clear()

        if direction in ("successors", "both"):
            _traverse_successors(item_id)

        # Sort by creation time
        results.sort(key=lambda x: x.created_at)
        return results

    async def get_lineage_chain(
        self,
        item_id: str,
        tenant_id: str | None = None,
    ) -> list[str]:
        """
        Get the full lineage chain as a list of IDs from oldest to newest.

        Args:
            item_id: Knowledge item ID
            tenant_id: Tenant ID

        Returns:
            Ordered list of IDs [oldest_ancestor, ..., current, ..., newest_successor]
        """
        lineage = await self.get_lineage(item_id, "both", tenant_id)

        # Build chain from lineage nodes
        predecessors = []
        successors = []

        current = item_id
        for node in lineage:
            if node.current_id == current and node.predecessor_id:
                predecessors.append(node.predecessor_id)
                current = node.predecessor_id
            elif node.predecessor_id == item_id:
                successors.append(node.current_id)

        # Reverse predecessors to get oldest first
        predecessors.reverse()

        return predecessors + [item_id] + successors

    # =========================================================================
    # Graph Traversal
    # =========================================================================

    async def traverse(
        self,
        start_id: str,
        relationship_types: list[RelationshipType] | None = None,
        max_depth: int = 3,
        direction: Literal["outgoing", "incoming", "both"] = "both",
        tenant_id: str | None = None,
    ) -> GraphTraversalResult:
        """
        Traverse the knowledge graph using BFS.

        Args:
            start_id: Starting node ID
            relationship_types: Filter by relationship types
            max_depth: Maximum traversal depth
            direction: Direction of traversal
            tenant_id: Tenant ID

        Returns:
            Traversal result with nodes and edges
        """
        tenant_id = tenant_id or self._default_tenant_id
        type_strs = [r.value for r in relationship_types] if relationship_types else None

        return await asyncio.to_thread(
            self._sync_traverse,
            start_id,
            type_strs,
            max_depth,
            direction,
            tenant_id,
        )

    def _sync_traverse(
        self,
        start_id: str,
        relationship_types: list[str] | None,
        max_depth: int,
        direction: str,
        tenant_id: str,
    ) -> GraphTraversalResult:
        """Synchronous BFS traversal."""
        from collections import deque

        visited_nodes = {start_id}
        visited_edges = set()
        all_edges = []

        queue = deque([(start_id, 0)])  # (node_id, depth)

        while queue:
            current_id, depth = queue.popleft()

            if depth >= max_depth:
                continue

            links = self._sync_get_links(current_id, relationship_types, direction, tenant_id)

            for link in links:
                if link.id not in visited_edges:
                    visited_edges.add(link.id)
                    all_edges.append(link)

                # Get the neighbor node
                neighbor = link.target_id if link.source_id == current_id else link.source_id

                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return GraphTraversalResult(
            nodes=list(visited_nodes),
            edges=all_edges,
            root_id=start_id,
            depth=max_depth,
            total_nodes=len(visited_nodes),
            total_edges=len(all_edges),
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self, tenant_id: str | None = None) -> dict:
        """Get statistics about the knowledge graph."""
        return await asyncio.to_thread(self._sync_get_stats, tenant_id or self._default_tenant_id)

    def _sync_get_stats(self, tenant_id: str) -> dict:
        """Synchronous stats retrieval."""
        total_links = self.fetch_one(
            "SELECT COUNT(*) FROM knowledge_links WHERE tenant_id = ?",
            (tenant_id,),
        )

        by_relationship = self.fetch_all(
            """
            SELECT relationship, COUNT(*) FROM knowledge_links
            WHERE tenant_id = ?
            GROUP BY relationship
            """,
            (tenant_id,),
        )

        total_lineage = self.fetch_one(
            "SELECT COUNT(*) FROM belief_lineage WHERE tenant_id = ?",
            (tenant_id,),
        )

        # Nodes with most connections
        hub_nodes = self.fetch_all(
            """
            SELECT node_id, COUNT(*) as connection_count FROM (
                SELECT source_id as node_id FROM knowledge_links WHERE tenant_id = ?
                UNION ALL
                SELECT target_id as node_id FROM knowledge_links WHERE tenant_id = ?
            )
            GROUP BY node_id
            ORDER BY connection_count DESC
            LIMIT 10
            """,
            (tenant_id, tenant_id),
        )

        return {
            "total_links": total_links[0] if total_links else 0,
            "by_relationship": dict(by_relationship),
            "total_lineage_entries": total_lineage[0] if total_lineage else 0,
            "hub_nodes": [{"node_id": r[0], "connections": r[1]} for r in hub_nodes],
            "tenant_id": tenant_id,
        }


__all__ = [
    "KnowledgeGraphStore",
    "GraphLink",
    "LineageNode",
    "GraphTraversalResult",
]
