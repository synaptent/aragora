"""
Memory Streams for persistent agent memory.

Inspired by Stanford Generative Agents, this module provides:
- Persistent memory across debates
- Memory types: observations, reflections, insights
- Retrieval by recency, importance, and relevance
- Periodic reflection to synthesize higher-level insights
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Optional, cast

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.exceptions import ConfigurationError
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.storage.base_store import SQLiteStore
from aragora.utils.async_utils import run_async
from aragora.utils.cache_registry import register_lru_cache
from aragora.utils.json_helpers import safe_json_loads

if TYPE_CHECKING:
    from aragora.memory.embeddings import EmbeddingProvider

# Module-level reference for embedding provider (used by cached function)
_embedding_provider_ref: Optional["EmbeddingProvider"] = None
_provider_registered = False


def _register_embedding_provider(provider: "EmbeddingProvider") -> None:
    """Register embedding provider with ServiceRegistry for observability."""
    global _provider_registered, _embedding_provider_ref
    if _embedding_provider_ref is not provider:
        _get_cached_embedding.cache_clear()
    _embedding_provider_ref = provider

    try:
        from aragora.embeddings.service_markers import EmbeddingProviderService
        from aragora.runtime.service_registry import ServiceRegistry

        registry = ServiceRegistry.get()
        registry.register(EmbeddingProviderService, provider)
        _provider_registered = True
    except ImportError:
        pass  # Services module not available


def get_embedding_provider() -> Optional["EmbeddingProvider"]:
    """Get the current embedding provider from registry or module-level ref."""
    global _embedding_provider_ref

    # Try ServiceRegistry first
    try:
        from aragora.embeddings.service_markers import EmbeddingProviderService
        from aragora.runtime.service_registry import ServiceRegistry

        registry = ServiceRegistry.get()
        if registry.has(EmbeddingProviderService):
            return cast("EmbeddingProvider", registry.resolve(EmbeddingProviderService))
    except ImportError:
        pass

    # Fall back to module-level reference
    return _embedding_provider_ref


@register_lru_cache
@lru_cache(maxsize=1000)
def _get_cached_embedding(content: str) -> tuple[float, ...]:
    """
    Get embedding with bounded LRU caching (max 1000 entries ~6MB).

    Uses module-level provider reference to enable @lru_cache decorator.
    Returns tuple for hashability in cache.
    """
    provider = get_embedding_provider()
    if provider is None:
        raise ConfigurationError(
            component="EmbeddingProvider",
            reason="Provider not initialized. Call set_embedding_provider() first",
        )
    # Use run_async() for safe sync/async bridging
    result = run_async(provider.embed(content))
    return tuple(result)


logger = logging.getLogger(__name__)


@dataclass
class Memory:
    """A single memory unit."""

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
        created = datetime.fromisoformat(self.created_at)
        now = datetime.now()
        return (now - created).total_seconds() / 3600


@dataclass
class RetrievedMemory:
    """A memory with retrieval score."""

    memory: Memory
    recency_score: float
    importance_score: float
    relevance_score: float

    @property
    def total_score(self) -> float:
        """Combined retrieval score."""
        # Weights can be tuned
        return 0.3 * self.recency_score + 0.3 * self.importance_score + 0.4 * self.relevance_score


class MemoryStream(SQLiteStore):
    """
    Persistent memory stream for an agent.

    Stores observations, reflections, and insights across debates.
    Supports retrieval by recency, importance, and relevance.

    Inherits from SQLiteStore for standardized schema management.
    """

    SCHEMA_NAME = "memory_stream"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Memory storage
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            debate_id TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_memories_agent
        ON memories(agent_name);

        CREATE INDEX IF NOT EXISTS idx_memories_type
        ON memories(agent_name, memory_type);

        -- Reflection schedule tracking
        CREATE TABLE IF NOT EXISTS reflection_schedule (
            agent_name TEXT PRIMARY KEY,
            last_reflection TEXT,
            memories_since_reflection INTEGER DEFAULT 0
        );
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        embedding_provider: Optional["EmbeddingProvider"] = None,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.CONTINUUM_MEMORY)
        super().__init__(db_path, timeout=DB_TIMEOUT_SECONDS)
        self.embedding_provider = embedding_provider
        # Register provider with ServiceRegistry for cached embedding function
        if embedding_provider is not None:
            _register_embedding_provider(embedding_provider)

    def _generate_id(self, agent_name: str, content: str) -> str:
        """Generate unique memory ID."""
        timestamp = datetime.now().isoformat()
        raw = f"{agent_name}:{content}:{timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def add(
        self,
        agent_name: str,
        content: str,
        memory_type: str = "observation",
        importance: float = 0.5,
        debate_id: str | None = None,
        metadata: dict | None = None,
    ) -> Memory:
        """
        Add a memory to the stream.

        Args:
            agent_name: Name of the agent
            content: The memory content
            memory_type: "observation", "reflection", or "insight"
            importance: 0-1 importance score
            debate_id: Optional debate this memory is from
            metadata: Optional additional data

        Returns:
            The created Memory object
        """
        memory_id = self._generate_id(agent_name, content)
        created_at = datetime.now().isoformat()

        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO memories (id, agent_name, memory_type, content, importance, debate_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    agent_name,
                    memory_type,
                    content,
                    importance,
                    debate_id,
                    json.dumps(metadata or {}),
                    created_at,
                ),
            )

            # Update reflection schedule
            cursor.execute(
                """
                INSERT INTO reflection_schedule (agent_name, memories_since_reflection)
                VALUES (?, 1)
                ON CONFLICT(agent_name) DO UPDATE SET
                    memories_since_reflection = memories_since_reflection + 1
                """,
                (agent_name,),
            )

        return Memory(
            id=memory_id,
            agent_name=agent_name,
            memory_type=memory_type,
            content=content,
            importance=importance,
            created_at=created_at,
            debate_id=debate_id,
            metadata=metadata or {},
        )

    def observe(
        self, agent_name: str, content: str, debate_id: str | None = None, importance: float = 0.5
    ) -> Memory:
        """Record an observation (convenience method)."""
        return self.add(agent_name, content, "observation", importance, debate_id)

    def reflect(self, agent_name: str, content: str, importance: float = 0.7) -> Memory:
        """Record a reflection (convenience method)."""
        return self.add(agent_name, content, "reflection", importance)

    def insight(self, agent_name: str, content: str, importance: float = 0.9) -> Memory:
        """Record an insight (convenience method)."""
        return self.add(agent_name, content, "insight", importance)

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
            agent_name: Name of the agent
            query: Optional query for relevance scoring
            memory_type: Filter by type
            limit: Maximum memories to return
            min_importance: Minimum importance threshold

        Returns:
            List of RetrievedMemory objects sorted by score
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            sql = """
                SELECT id, agent_name, memory_type, content, importance, debate_id, metadata, created_at
                FROM memories
                WHERE agent_name = ? AND importance >= ?
            """
            params = [agent_name, min_importance]

            if memory_type:
                sql += " AND memory_type = ?"
                params.append(memory_type)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit * 3)  # Fetch more for scoring

            cursor.execute(sql, params)
            rows = cursor.fetchall()

        memories = []
        for row in rows:
            memory = Memory(
                id=row[0],
                agent_name=row[1],
                memory_type=row[2],
                content=row[3],
                importance=row[4],
                debate_id=row[5],
                metadata=safe_json_loads(row[6], {}),
                created_at=row[7],
            )

            # Calculate scores
            recency_score = self._recency_score(memory)
            importance_score = memory.importance
            relevance_score = self._relevance_score(memory.content, query) if query else 0.5

            memories.append(
                RetrievedMemory(
                    memory=memory,
                    recency_score=recency_score,
                    importance_score=importance_score,
                    relevance_score=relevance_score,
                )
            )

        # Sort by total score and limit
        memories.sort(key=lambda m: m.total_score, reverse=True)
        return memories[:limit]

    def _recency_score(self, memory: Memory) -> float:
        """Calculate recency score (exponential decay)."""
        hours = memory.age_hours
        # Half-life of 24 hours
        return 0.5 ** (hours / 24)

    def _relevance_score(self, content: str, query: str) -> float:
        """
        Calculate relevance score using embeddings or keyword matching.

        Uses semantic similarity via embeddings when available, otherwise
        falls back to simple keyword matching.
        """
        if not query:
            return 0.5

        # Try embedding-based similarity if provider available
        if self.embedding_provider:
            try:
                return self._embedding_similarity(content, query)
            except (ValueError, TypeError, RuntimeError, OSError) as e:
                logger.debug("[memory] Embedding similarity failed, using keyword fallback: %s", e)
            except Exception as e:
                logger.debug("[memory] Embedding similarity failed, using keyword fallback: %s", e)

        # Keyword matching fallback
        # Limit to 50 words to prevent O(n*m) CPU exhaustion
        MAX_QUERY_WORDS = 50
        content_lower = content.lower()
        query_words = query.lower().split()[:MAX_QUERY_WORDS]

        matches = sum(1 for word in query_words if word in content_lower)
        return min(1.0, matches / max(len(query_words), 1))

    def _embedding_similarity(self, content: str, query: str) -> float:
        """Calculate cosine similarity between content and query embeddings."""
        from aragora.memory.embeddings import cosine_similarity

        # Get embeddings using bounded LRU cache (max 1000 entries)
        content_embedding = _get_cached_embedding(content[:500])
        query_embedding = _get_cached_embedding(query)

        # Compute similarity (convert tuples back to lists for cosine_similarity)
        return cosine_similarity(list(content_embedding), list(query_embedding))

    def get_recent(self, agent_name: str, limit: int = 20) -> list[Memory]:
        """Get most recent memories for an agent."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, agent_name, memory_type, content, importance, debate_id, metadata, created_at
                FROM memories
                WHERE agent_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_name, limit),
            )

            memories = [
                Memory(
                    id=row[0],
                    agent_name=row[1],
                    memory_type=row[2],
                    content=row[3],
                    importance=row[4],
                    debate_id=row[5],
                    metadata=safe_json_loads(row[6], {}),
                    created_at=row[7],
                )
                for row in cursor.fetchall()
            ]

        return memories

    def should_reflect(self, agent_name: str, threshold: int = 10) -> bool:
        """Check if agent should perform reflection."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT memories_since_reflection FROM reflection_schedule WHERE agent_name = ?",
                (agent_name,),
            )
            row = cursor.fetchone()

        return row is not None and row[0] >= threshold

    def mark_reflected(self, agent_name: str) -> None:
        """Mark that agent has performed reflection."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE reflection_schedule
                SET last_reflection = ?, memories_since_reflection = 0
                WHERE agent_name = ?
                """,
                (datetime.now().isoformat(), agent_name),
            )

            conn.commit()

    def generate_reflection_prompt(self, agent_name: str, limit: int = 20) -> str:
        """
        Generate a prompt for the agent to reflect on recent memories.

        Returns a prompt that can be sent to the agent to generate reflections.
        """
        recent = self.get_recent(agent_name, limit)

        if not recent:
            return ""

        memories_text = "\n".join([f"- [{m.memory_type}] {m.content}" for m in recent])

        return f"""Based on your recent experiences, reflect on what you've learned.

Recent memories:
{memories_text}

Synthesize 2-3 higher-level insights about:
1. What patterns do you notice in your critiques/responses?
2. What types of issues do you catch most effectively?
3. What areas could you improve?

Format each insight on a new line starting with "INSIGHT:"
"""

    def parse_reflections(self, agent_name: str, response: str) -> list[Memory]:
        """Parse reflection response and store insights."""
        insights = []

        for line in response.split("\n"):
            line = line.strip()
            if line.upper().startswith("INSIGHT:"):
                content = line[8:].strip()
                if content:
                    memory = self.insight(agent_name, content)
                    insights.append(memory)

        if insights:
            self.mark_reflected(agent_name)

        return insights

    def get_context_for_debate(self, agent_name: str, task: str, limit: int = 5) -> str:
        """
        Get relevant context from memory for a debate.

        Returns a formatted string to include in the agent's prompt.
        """
        # Get relevant memories
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

    def get_stats(self, agent_name: str) -> dict:
        """Get memory statistics for an agent."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
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

            row = cursor.fetchone()

        return {
            "total_memories": row[0] or 0,
            "observations": row[1] or 0,
            "reflections": row[2] or 0,
            "insights": row[3] or 0,
            "avg_importance": row[4] or 0.0,
        }
