"""
Memory Repository for agent memory persistence.

Provides repository pattern access to agent memories including:
- Observations, reflections, and insights
- Reflection scheduling
- Memory retrieval with scoring
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.persistence.db_config import DatabaseType, get_db_path

from .base import BaseRepository

logger = logging.getLogger(__name__)

# =============================================================================
# Memory Entities
# =============================================================================


@dataclass
class MemoryEntity:
    """A single memory unit stored in the database."""

    id: str
    agent_name: str
    memory_type: str  # "observation", "reflection", "insight"
    content: str
    importance: float  # 0-1 scale
    created_at: str
    debate_id: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def age_hours(self) -> float:
        """Hours since memory was created."""
        try:
            created = datetime.fromisoformat(self.created_at)
            now = datetime.now()
            return (now - created).total_seconds() / 3600
        except (ValueError, TypeError):
            return 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "memory_type": self.memory_type,
            "content": self.content,
            "importance": self.importance,
            "created_at": self.created_at,
            "debate_id": self.debate_id,
            "metadata": self.metadata,
        }


@dataclass
class ReflectionSchedule:
    """Tracks when an agent should perform reflection."""

    agent_name: str
    last_reflection: str | None = None
    memories_since_reflection: int = 0


@dataclass
class RetrievedMemory:
    """A memory with retrieval scores for ranking."""

    memory: MemoryEntity
    recency_score: float
    importance_score: float
    relevance_score: float

    @property
    def total_score(self) -> float:
        """Combined retrieval score with default weights."""
        return 0.3 * self.recency_score + 0.3 * self.importance_score + 0.4 * self.relevance_score


# =============================================================================
# Memory Repository
# =============================================================================


class MemoryRepository(BaseRepository[MemoryEntity]):
    """
    Repository for agent memory persistence.

    Handles CRUD operations for memories and reflection scheduling.
    Provides retrieval with recency/importance/relevance scoring.

    Usage:
        repo = MemoryRepository()

        # Add a memory
        memory = repo.add_memory(
            agent_name="claude",
            content="Learned that concise critiques are more effective",
            memory_type="insight",
            importance=0.8,
        )

        # Retrieve relevant memories
        memories = repo.retrieve(
            agent_name="claude",
            query="effective critique strategies",
            limit=5,
        )

        # Check if reflection is needed
        if repo.should_reflect("claude"):
            # ... perform reflection
            repo.mark_reflected("claude")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize the memory repository.

        Args:
            db_path: Path to the memory database file. Defaults to get_db_path(DatabaseType.CONTINUUM_MEMORY).
        """
        if db_path is None:
            db_path = get_db_path(DatabaseType.CONTINUUM_MEMORY)
        super().__init__(db_path)

    @property
    def _table_name(self) -> str:
        return "memories"

    @property
    def _entity_name(self) -> str:
        return "Memory"

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._transaction() as conn:
            # Memories table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    debate_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_agent
                ON memories(agent_name)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_type
                ON memories(agent_name, memory_type)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_importance
                ON memories(agent_name, importance DESC)
            """)

            # Reflection schedule table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reflection_schedule (
                    agent_name TEXT PRIMARY KEY,
                    last_reflection TEXT,
                    memories_since_reflection INTEGER DEFAULT 0
                )
            """)

    def _to_entity(self, row: sqlite3.Row) -> MemoryEntity:
        """Convert database row to MemoryEntity."""
        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Failed to parse memory metadata for row %s: %s", row["id"], e)

        return MemoryEntity(
            id=row["id"],
            agent_name=row["agent_name"],
            memory_type=row["memory_type"],
            content=row["content"],
            importance=row["importance"] or 0.5,
            created_at=row["created_at"] or datetime.now().isoformat(),
            debate_id=row["debate_id"],
            metadata=metadata,
        )

    def _from_entity(self, entity: MemoryEntity) -> dict[str, Any]:
        """Convert MemoryEntity to database columns."""
        return {
            "id": entity.id,
            "agent_name": entity.agent_name,
            "memory_type": entity.memory_type,
            "content": entity.content,
            "importance": entity.importance,
            "debate_id": entity.debate_id,
            "metadata": json.dumps(entity.metadata),
            "created_at": entity.created_at,
        }

    def _generate_id(self, agent_name: str, content: str) -> str:
        """Generate unique memory ID."""
        timestamp = datetime.now().isoformat()
        raw = f"{agent_name}:{content}:{timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # =========================================================================
    # Memory Operations
    # =========================================================================

    def add_memory(
        self,
        agent_name: str,
        content: str,
        memory_type: str = "observation",
        importance: float = 0.5,
        debate_id: str | None = None,
        metadata: dict | None = None,
    ) -> MemoryEntity:
        """
        Add a new memory.

        Args:
            agent_name: Name of the agent
            content: The memory content
            memory_type: "observation", "reflection", or "insight"
            importance: 0-1 importance score
            debate_id: Optional debate this memory is from
            metadata: Optional additional data

        Returns:
            The created MemoryEntity
        """
        memory_id = self._generate_id(agent_name, content)
        created_at = datetime.now().isoformat()

        memory = MemoryEntity(
            id=memory_id,
            agent_name=agent_name,
            memory_type=memory_type,
            content=content,
            importance=importance,
            created_at=created_at,
            debate_id=debate_id,
            metadata=metadata or {},
        )

        with self._transaction() as conn:
            # Insert memory
            conn.execute(
                """
                INSERT INTO memories (id, agent_name, memory_type, content, importance, debate_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.agent_name,
                    memory.memory_type,
                    memory.content,
                    memory.importance,
                    memory.debate_id,
                    json.dumps(memory.metadata),
                    memory.created_at,
                ),
            )

            # Update reflection schedule
            conn.execute(
                """
                INSERT INTO reflection_schedule (agent_name, memories_since_reflection)
                VALUES (?, 1)
                ON CONFLICT(agent_name) DO UPDATE SET
                    memories_since_reflection = memories_since_reflection + 1
                """,
                (agent_name,),
            )

        return memory

    def observe(
        self,
        agent_name: str,
        content: str,
        debate_id: str | None = None,
        importance: float = 0.5,
    ) -> MemoryEntity:
        """Record an observation (convenience method)."""
        return self.add_memory(agent_name, content, "observation", importance, debate_id)

    def reflect(self, agent_name: str, content: str, importance: float = 0.7) -> MemoryEntity:
        """Record a reflection (convenience method)."""
        return self.add_memory(agent_name, content, "reflection", importance)

    def insight(self, agent_name: str, content: str, importance: float = 0.9) -> MemoryEntity:
        """Record an insight (convenience method)."""
        return self.add_memory(agent_name, content, "insight", importance)

    def get_by_agent(
        self,
        agent_name: str,
        memory_type: str | None = None,
        limit: int = 100,
        min_importance: float = 0.0,
    ) -> list[MemoryEntity]:
        """
        Get memories for an agent.

        Args:
            agent_name: Agent to get memories for
            memory_type: Optional filter by type
            limit: Maximum memories to return
            min_importance: Minimum importance threshold

        Returns:
            List of memories ordered by creation time (newest first)
        """
        sql = """
            SELECT * FROM memories
            WHERE agent_name = ? AND importance >= ?
        """
        params: list = [agent_name, min_importance]

        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._fetch_all(sql, tuple(params))
        return [self._to_entity(row) for row in rows]

    def retrieve(
        self,
        agent_name: str,
        query: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[RetrievedMemory]:
        """
        Retrieve memories ranked by recency, importance, and relevance.

        Args:
            agent_name: Agent to retrieve memories for
            query: Optional query for relevance scoring
            memory_type: Optional filter by type
            limit: Maximum memories to return
            min_importance: Minimum importance threshold

        Returns:
            List of RetrievedMemory sorted by total score
        """
        # Fetch more than limit for scoring
        memories = self.get_by_agent(
            agent_name,
            memory_type=memory_type,
            limit=limit * 3,
            min_importance=min_importance,
        )

        retrieved = []
        for memory in memories:
            recency_score = self._recency_score(memory)
            importance_score = memory.importance
            relevance_score = self._relevance_score(memory.content, query) if query else 0.5

            retrieved.append(
                RetrievedMemory(
                    memory=memory,
                    recency_score=recency_score,
                    importance_score=importance_score,
                    relevance_score=relevance_score,
                )
            )

        # Sort by total score and limit
        retrieved.sort(key=lambda m: m.total_score, reverse=True)
        return retrieved[:limit]

    def _recency_score(self, memory: MemoryEntity) -> float:
        """Calculate recency score with 24-hour half-life."""
        hours = memory.age_hours
        return 0.5 ** (hours / 24)

    def _relevance_score(self, content: str, query: str | None) -> float:
        """Calculate relevance score using keyword matching."""
        if not query:
            return 0.5

        content_lower = content.lower()
        query_words = query.lower().split()

        matches = sum(1 for word in query_words if word in content_lower)
        return min(1.0, matches / max(len(query_words), 1))

    # =========================================================================
    # Reflection Scheduling
    # =========================================================================

    def should_reflect(self, agent_name: str, threshold: int = 10) -> bool:
        """Check if agent should perform reflection."""
        row = self._fetch_one(
            "SELECT memories_since_reflection FROM reflection_schedule WHERE agent_name = ?",
            (agent_name,),
        )
        return row is not None and row[0] >= threshold

    def mark_reflected(self, agent_name: str) -> None:
        """Mark that agent has performed reflection."""
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE reflection_schedule
                SET last_reflection = ?, memories_since_reflection = 0
                WHERE agent_name = ?
                """,
                (datetime.now().isoformat(), agent_name),
            )

    def get_reflection_schedule(self, agent_name: str) -> ReflectionSchedule | None:
        """Get reflection schedule for an agent."""
        row = self._fetch_one(
            "SELECT * FROM reflection_schedule WHERE agent_name = ?",
            (agent_name,),
        )
        if not row:
            return None

        return ReflectionSchedule(
            agent_name=row["agent_name"],
            last_reflection=row["last_reflection"],
            memories_since_reflection=row["memories_since_reflection"] or 0,
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self, agent_name: str) -> dict:
        """Get memory statistics for an agent."""
        row = self._fetch_one(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN memory_type = 'observation' THEN 1 ELSE 0 END) as observations,
                SUM(CASE WHEN memory_type = 'reflection' THEN 1 ELSE 0 END) as reflections,
                SUM(CASE WHEN memory_type = 'insight' THEN 1 ELSE 0 END) as insights,
                AVG(importance) as avg_importance
            FROM memories
            WHERE agent_name = ?
            """,
            (agent_name,),
        )

        if row is None:
            return {
                "total_memories": 0,
                "observations": 0,
                "reflections": 0,
                "insights": 0,
                "avg_importance": 0.0,
            }

        return {
            "total_memories": row[0] or 0,
            "observations": row[1] or 0,
            "reflections": row[2] or 0,
            "insights": row[3] or 0,
            "avg_importance": row[4] or 0.0,
        }

    def get_context_for_debate(self, agent_name: str, task: str, limit: int = 5) -> str:
        """
        Get relevant context from memory for a debate.

        Returns a formatted string to include in the agent's prompt.
        """
        retrieved = self.retrieve(agent_name, query=task, limit=limit, min_importance=0.3)

        if not retrieved:
            return ""

        context_parts = []
        for rm in retrieved:
            m = rm.memory
            if m.memory_type == "insight":
                context_parts.append(f"[Insight] {m.content}")
            elif m.memory_type == "reflection":
                context_parts.append(f"[Learning] {m.content}")
            else:
                context_parts.append(f"[Experience] {m.content}")

        return "Relevant past experience:\n" + "\n".join(context_parts)

    def delete_by_agent(self, agent_name: str) -> int:
        """Delete all memories for an agent. Returns count deleted."""
        with self._transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE agent_name = ?",
                (agent_name,),
            )
            # Also clear reflection schedule
            conn.execute(
                "DELETE FROM reflection_schedule WHERE agent_name = ?",
                (agent_name,),
            )
            return cursor.rowcount
