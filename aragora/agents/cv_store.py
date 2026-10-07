"""
Agent CV persistent storage.

Stores and retrieves AgentCV instances with caching and TTL support.
Uses SQLite for persistence, compatible with existing storage patterns.

Example:
    from aragora.agents.cv_store import CVStore

    store = CVStore()
    await store.save_cv(cv)
    cv = await store.get_cv("claude-opus")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from aragora.agents.cv import AgentCV, CVBuilder, get_cv_builder
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.storage.base_store import SQLiteStore
from aragora.config import DB_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

__all__ = [
    "CVStore",
    "get_cv_store",
]

# Schema version for migrations
CV_SCHEMA_VERSION = 1

# Default cache TTL (5 minutes)
DEFAULT_CACHE_TTL_SECONDS = 300


class CVStore(SQLiteStore):
    """
    Persistent storage for Agent CVs.

    Provides:
    - SQLite-backed persistence
    - In-memory caching with TTL
    - Automatic refresh from data sources
    - Batch operations

    Example:
        store = CVStore()

        # Get CV (auto-builds if not cached)
        cv = await store.get_cv("claude-opus")

        # Force refresh from data sources
        cv = await store.refresh_cv("claude-opus")

        # Get multiple CVs
        cvs = await store.get_cvs_batch(["claude", "gpt-4", "gemini"])
    """

    SCHEMA_NAME = "agent_cv"
    SCHEMA_VERSION = CV_SCHEMA_VERSION

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS agent_cvs (
            agent_id TEXT PRIMARY KEY,
            cv_data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_cv_updated ON agent_cvs(updated_at);
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        cv_builder: CVBuilder | None = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.AGENT_MEMORIES)
        super().__init__(db_path, timeout=DB_TIMEOUT_SECONDS)

        self._cv_builder = cv_builder
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache: dict[str, tuple[datetime, AgentCV]] = {}

    @property
    def cv_builder(self) -> CVBuilder:
        """Get the CV builder (lazy initialization)."""
        if self._cv_builder is None:
            self._cv_builder = get_cv_builder()
        return self._cv_builder

    def _is_cache_valid(self, agent_id: str) -> bool:
        """Check if cached CV is still valid."""
        if agent_id not in self._cache:
            return False
        cached_time, _ = self._cache[agent_id]
        return datetime.now() - cached_time < self._cache_ttl

    async def get_cv(
        self,
        agent_id: str,
        use_cache: bool = True,
        auto_build: bool = True,
    ) -> AgentCV | None:
        """
        Get CV for an agent.

        Args:
            agent_id: Agent identifier
            use_cache: Use cached CV if available and fresh
            auto_build: Build CV from data sources if not found

        Returns:
            AgentCV or None if not found and auto_build is False
        """
        # Check cache first
        if use_cache and self._is_cache_valid(agent_id):
            _, cv = self._cache[agent_id]
            return cv

        # Check database
        loaded_cv = self._load_from_db(agent_id)
        if loaded_cv is not None:
            # Check if stale
            age = datetime.now() - loaded_cv.updated_at
            if age < self._cache_ttl:
                self._cache[agent_id] = (datetime.now(), loaded_cv)
                return loaded_cv

        # Build from data sources
        if auto_build:
            built_cv = self.cv_builder.build_cv(agent_id)
            await self.save_cv(built_cv)
            return built_cv

        return loaded_cv

    def get_cv_sync(
        self,
        agent_id: str,
        use_cache: bool = True,
        auto_build: bool = True,
    ) -> AgentCV | None:
        """
        Synchronous version of get_cv for non-async contexts.

        Args:
            agent_id: Agent identifier
            use_cache: Use cached CV if available and fresh
            auto_build: Build CV from data sources if not found

        Returns:
            AgentCV or None if not found and auto_build is False
        """
        # Check cache first
        if use_cache and self._is_cache_valid(agent_id):
            _, cv = self._cache[agent_id]
            return cv

        # Check database
        loaded_cv = self._load_from_db(agent_id)
        if loaded_cv is not None:
            # Check if stale
            age = datetime.now() - loaded_cv.updated_at
            if age < self._cache_ttl:
                self._cache[agent_id] = (datetime.now(), loaded_cv)
                return loaded_cv

        # Build from data sources
        if auto_build:
            built_cv = self.cv_builder.build_cv(agent_id)
            self._save_to_db(built_cv)
            self._cache[agent_id] = (datetime.now(), built_cv)
            return built_cv

        return loaded_cv

    async def save_cv(self, cv: AgentCV) -> None:
        """
        Save CV to database and cache.

        Args:
            cv: AgentCV to save
        """
        self._save_to_db(cv)
        self._cache[cv.agent_id] = (datetime.now(), cv)

    async def refresh_cv(self, agent_id: str) -> AgentCV:
        """
        Force refresh CV from data sources.

        Args:
            agent_id: Agent identifier

        Returns:
            Freshly built AgentCV
        """
        cv = self.cv_builder.build_cv(agent_id)
        await self.save_cv(cv)
        return cv

    async def get_cvs_batch(
        self,
        agent_ids: list[str],
        use_cache: bool = True,
        auto_build: bool = True,
    ) -> dict[str, AgentCV]:
        """
        Get CVs for multiple agents efficiently.

        Args:
            agent_ids: List of agent identifiers
            use_cache: Use cached CVs if available
            auto_build: Build CVs from data sources if not found

        Returns:
            Dict mapping agent_id to AgentCV
        """
        result = {}
        to_load = []
        to_build = []

        # Check cache first
        for agent_id in agent_ids:
            if use_cache and self._is_cache_valid(agent_id):
                _, cv = self._cache[agent_id]
                result[agent_id] = cv
            else:
                to_load.append(agent_id)

        # Load from database
        if to_load:
            for agent_id in to_load:
                loaded_cv = self._load_from_db(agent_id)
                if loaded_cv is not None:
                    age = datetime.now() - loaded_cv.updated_at
                    if age < self._cache_ttl:
                        result[agent_id] = loaded_cv
                        self._cache[agent_id] = (datetime.now(), loaded_cv)
                    else:
                        to_build.append(agent_id)
                elif auto_build:
                    to_build.append(agent_id)

        # Build missing CVs
        if to_build and auto_build:
            built_cvs = self.cv_builder.build_cvs_batch(to_build)
            for agent_id, cv in built_cvs.items():
                await self.save_cv(cv)
                result[agent_id] = cv

        return result

    async def delete_cv(self, agent_id: str) -> bool:
        """
        Delete CV from database and cache.

        Args:
            agent_id: Agent identifier

        Returns:
            True if CV was deleted
        """
        # Remove from cache
        self._cache.pop(agent_id, None)

        # Remove from database
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_cvs WHERE agent_id = ?",
                (agent_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def invalidate_cache(self, agent_id: str | None = None) -> int:
        """
        Invalidate cached CVs.

        Args:
            agent_id: Specific agent to invalidate, or None for all

        Returns:
            Number of entries invalidated
        """
        if agent_id is not None:
            if agent_id in self._cache:
                del self._cache[agent_id]
                return 1
            return 0

        count = len(self._cache)
        self._cache.clear()
        return count

    def _load_from_db(self, agent_id: str) -> AgentCV | None:
        """Load CV from database."""
        try:
            with self.connection() as conn:
                cursor = conn.execute(
                    "SELECT cv_data FROM agent_cvs WHERE agent_id = ?",
                    (agent_id,),
                )
                row = cursor.fetchone()

            if row:
                data = json.loads(row[0])
                return AgentCV.from_dict(data)
            return None
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            logger.warning("Failed to load CV from database for %s: %s", agent_id, e)
            return None

    def _save_to_db(self, cv: AgentCV) -> None:
        """Save CV to database."""
        try:
            cv_data = json.dumps(cv.to_dict())
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agent_cvs (agent_id, cv_data, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (cv.agent_id, cv_data, datetime.now().isoformat()),
                )
                conn.commit()
        except (TypeError, ValueError, OSError) as e:
            logger.warning("Failed to save CV to database for %s: %s", cv.agent_id, e)

    async def get_all_cvs(self, limit: int = 100) -> list[AgentCV]:
        """
        Get all stored CVs.

        Args:
            limit: Maximum number of CVs to return

        Returns:
            List of AgentCV instances
        """
        cvs = []
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT cv_data FROM agent_cvs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()

        for row in rows:
            try:
                data = json.loads(row[0])
                cv = AgentCV.from_dict(data)
                cvs.append(cv)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning("Failed to parse CV from database: %s", e)

        return cvs

    async def get_top_agents_for_domain(
        self,
        domain: str,
        limit: int = 10,
    ) -> list[AgentCV]:
        """
        Get top agents for a specific domain by composite score.

        Args:
            domain: Domain to rank agents for
            limit: Maximum number of agents to return

        Returns:
            List of AgentCV instances sorted by domain score
        """
        all_cvs = await self.get_all_cvs(limit=200)

        # Filter to agents with domain data and sort by score
        domain_cvs = [
            cv
            for cv in all_cvs
            if domain in cv.domain_performance and cv.domain_performance[domain].has_meaningful_data
        ]

        domain_cvs.sort(
            key=lambda cv: cv.domain_performance[domain].composite_score,
            reverse=True,
        )

        return domain_cvs[:limit]


# Singleton store instance
_cv_store: CVStore | None = None


def get_cv_store() -> CVStore:
    """Get the global CVStore singleton instance."""
    global _cv_store
    if _cv_store is None:
        _cv_store = CVStore()
    return _cv_store
