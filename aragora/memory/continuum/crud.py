"""
CRUD operations mixin for ContinuumMemory.

Provides add, get, update, delete operations for memory entries.
"""
# mypy: disable-error-code="misc"
# Mixin classes use self: "ContinuumMemory" type hints which mypy doesn't understand

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import MemoryTier
from aragora.resilience.retry import PROVIDER_RETRY_POLICIES, with_retry
from aragora.utils.datetime_helpers import utc_now_iso_naive
from aragora.utils.json_helpers import safe_json_loads

from .entry import ContinuumMemoryEntry

if TYPE_CHECKING:
    from .core import ContinuumMemory

logger = logging.getLogger(__name__)

# Retry configuration for memory operations
_MEMORY_RETRY_CONFIG = PROVIDER_RETRY_POLICIES["memory"]


class CrudMixin:
    """Mixin providing CRUD operations for ContinuumMemory."""

    def add(
        self: ContinuumMemory,
        id: str,
        content: str,
        tier: MemoryTier = MemoryTier.SLOW,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> ContinuumMemoryEntry:
        """
        Add a new memory entry to the continuum.

        Args:
            id: Unique identifier for the memory
            content: The memory content
            tier: Initial memory tier
            importance: 0-1 importance score
            metadata: Optional additional data
            tenant_id: Optional tenant ID for multi-tenant isolation.
                       When provided, stored in metadata for filtering.

        Returns:
            The created memory entry
        """
        now: str = utc_now_iso_naive()

        # Inject tenant_id into metadata for tenant isolation
        if tenant_id is not None:
            metadata = dict(metadata) if metadata else {}
            metadata["tenant_id"] = tenant_id

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO continuum_memory
                (id, tier, content, importance, surprise_score, consolidation_score,
                 update_count, success_count, failure_count, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, 0.0, 0.0, 1, 0, 0, ?, ?, ?)
                """,
                (id, tier.value, content, importance, now, now, json.dumps(metadata or {})),
            )
            conn.commit()

        entry: ContinuumMemoryEntry = ContinuumMemoryEntry(
            id=id,
            tier=tier,
            content=content,
            importance=importance,
            surprise_score=0.0,
            consolidation_score=0.0,
            update_count=1,
            success_count=0,
            failure_count=0,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        # Emit MEMORY_STORED event for cross-subsystem tracking
        if self.event_emitter:
            try:
                self.event_emitter.emit_sync(
                    event_type="memory_stored",
                    debate_id="",
                    memory_id=id,
                    tier=tier.value,
                    importance=importance,
                    content_length=len(content),
                )
            except (ImportError, AttributeError, TypeError):
                pass  # Events module not available

        # Sync to Knowledge Mound if adapter is configured and importance is high
        if self._km_adapter and importance >= 0.7:
            try:
                self._km_adapter.store_memory(entry)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.debug("Failed to sync memory to KM (network): %s", e)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Failed to sync memory to KM (data): %s", e)
            except (RuntimeError, AttributeError) as e:
                logger.warning("Unexpected error syncing memory to KM: %s", e)

        return entry

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def add_async(
        self: ContinuumMemory,
        id: str,
        content: str,
        tier: MemoryTier = MemoryTier.SLOW,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """Async wrapper for add() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.add(
                id=id,
                content=content,
                tier=tier,
                importance=importance,
                metadata=metadata,
            ),
        )

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def store(
        self: ContinuumMemory,
        key: str,
        content: str,
        tier: str | MemoryTier = MemoryTier.SLOW,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """Async wrapper for add() - offloads blocking I/O to executor."""
        normalized_tier: MemoryTier = MemoryTier(tier) if isinstance(tier, str) else tier
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.add(
                id=key,
                content=content,
                tier=normalized_tier,
                importance=importance,
                metadata=metadata,
            ),
        )

    def get(
        self: ContinuumMemory, id: str, tenant_id: str | None = None
    ) -> ContinuumMemoryEntry | None:
        """Get a memory entry by ID.

        Args:
            id: Memory entry ID
            tenant_id: Optional tenant ID for multi-tenant isolation.
                       When provided, only returns the entry if it belongs
                       to the specified tenant.
        """
        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tier, content, importance, surprise_score, consolidation_score,
                       update_count, success_count, failure_count, created_at, updated_at, metadata,
                       COALESCE(red_line, 0), COALESCE(red_line_reason, '')
                FROM continuum_memory
                WHERE id = ?
                """,
                (id,),
            )
            row: tuple[Any, ...] | None = cursor.fetchone()

        if not row:
            return None

        entry = ContinuumMemoryEntry(
            id=row[0],
            tier=MemoryTier(row[1]),
            content=row[2],
            importance=row[3],
            surprise_score=row[4],
            consolidation_score=row[5],
            update_count=row[6],
            success_count=row[7],
            failure_count=row[8],
            created_at=row[9],
            updated_at=row[10],
            metadata=safe_json_loads(row[11], {}),
            red_line=bool(row[12]),
            red_line_reason=row[13],
        )

        # Enforce tenant isolation: if tenant_id is specified, only return
        # entries belonging to that tenant
        if tenant_id is not None:
            entry_tenant = entry.metadata.get("tenant_id")
            if entry_tenant != tenant_id:
                return None

        return entry

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def get_async(self: ContinuumMemory, id: str) -> ContinuumMemoryEntry | None:
        """Async wrapper for get() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get, id)

    def get_entry(self: ContinuumMemory, id: str) -> ContinuumMemoryEntry | None:
        """Alias for get() for interface compatibility with OutcomeMemoryBridge."""
        return self.get(id)

    def update_entry(self: ContinuumMemory, entry: ContinuumMemoryEntry) -> bool:
        """Update an entry's success/failure counts.

        Interface compatibility method for OutcomeMemoryBridge.
        """
        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE continuum_memory
                SET success_count = ?, failure_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (entry.success_count, entry.failure_count, utc_now_iso_naive(), entry.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def update_entry_async(self: ContinuumMemory, entry: ContinuumMemoryEntry) -> bool:
        """Async wrapper for update_entry() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.update_entry, entry)

    def update(
        self: ContinuumMemory,
        memory_id: str,
        content: str | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        surprise_score: float | None = None,
        consolidation_score: float | None = None,
        tenant_id: str | None = None,
    ) -> bool:
        """Update specific fields of a memory entry.

        Flexible update method for modifying individual fields.
        Used by ContinuumAdapter for KM validation reverse flow.

        Args:
            memory_id: The ID of the memory entry to update
            content: New content (optional)
            importance: New importance score (optional)
            metadata: New metadata dict (optional, replaces existing)
            surprise_score: New surprise score (optional)
            consolidation_score: New consolidation score (optional)
            tenant_id: Optional tenant ID for multi-tenant isolation.
                       When provided, validates that the entry belongs to
                       the specified tenant before updating.

        Returns:
            True if the entry was updated, False if not found or tenant mismatch
        """
        # Validate tenant isolation before update
        if tenant_id is not None:
            existing = self.get(memory_id)
            if existing is None:
                return False
            entry_tenant = existing.metadata.get("tenant_id")
            if entry_tenant and entry_tenant != tenant_id:
                logger.warning(
                    "Cross-tenant update blocked: memory=%s entry_tenant=%s request_tenant=%s",
                    memory_id,
                    entry_tenant,
                    tenant_id,
                )
                return False
        # Build update clauses dynamically
        updates: list[str] = []
        params: list[Any] = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if importance is not None:
            updates.append("importance = ?")
            params.append(importance)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))
        if surprise_score is not None:
            updates.append("surprise_score = ?")
            params.append(surprise_score)
        if consolidation_score is not None:
            updates.append("consolidation_score = ?")
            params.append(consolidation_score)

        if not updates:
            return False

        # Always update timestamp
        updates.append("updated_at = ?")
        params.append(utc_now_iso_naive())

        # Add memory_id as final parameter
        params.append(memory_id)

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE continuum_memory
                SET {", ".join(updates)}
                WHERE id = ?
                """,  # noqa: S608 -- dynamic clause from internal state
                tuple(params),
            )
            conn.commit()
            return cursor.rowcount > 0

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def update_async(
        self: ContinuumMemory,
        memory_id: str,
        content: str | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        surprise_score: float | None = None,
        consolidation_score: float | None = None,
        tenant_id: str | None = None,
    ) -> bool:
        """Async wrapper for update() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.update(
                memory_id=memory_id,
                content=content,
                importance=importance,
                metadata=metadata,
                surprise_score=surprise_score,
                consolidation_score=consolidation_score,
                tenant_id=tenant_id,
            ),
        )

    def promote_entry(
        self: ContinuumMemory,
        memory_id: str,
        new_tier: MemoryTier,
        tenant_id: str | None = None,
    ) -> bool:
        """Promote an entry to a specific tier.

        Interface compatibility method for OutcomeMemoryBridge.

        Args:
            memory_id: The ID of the memory entry to promote
            new_tier: The target tier to promote to
            tenant_id: Optional tenant ID for multi-tenant isolation.
                       When provided, validates that the entry belongs to
                       the specified tenant before promoting.

        Returns:
            True if the entry was promoted, False if not found or tenant mismatch
        """
        # Validate tenant isolation before promotion
        if tenant_id is not None:
            existing = self.get(memory_id)
            if existing is None:
                return False
            entry_tenant = existing.metadata.get("tenant_id")
            if entry_tenant and entry_tenant != tenant_id:
                logger.warning(
                    "Cross-tenant promotion blocked: memory=%s entry_tenant=%s request_tenant=%s",
                    memory_id,
                    entry_tenant,
                    tenant_id,
                )
                return False

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE continuum_memory
                SET tier = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_tier.value, utc_now_iso_naive(), memory_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def promote_entry_async(
        self: ContinuumMemory,
        memory_id: str,
        new_tier: MemoryTier,
        tenant_id: str | None = None,
    ) -> bool:
        """Async wrapper for promote_entry() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.promote_entry(memory_id, new_tier, tenant_id)
        )

    def demote_entry(
        self: ContinuumMemory,
        memory_id: str,
        new_tier: MemoryTier,
        tenant_id: str | None = None,
    ) -> bool:
        """Demote an entry to a specific tier.

        Interface compatibility method for OutcomeMemoryBridge.

        Args:
            memory_id: The ID of the memory entry to demote
            new_tier: The target tier to demote to
            tenant_id: Optional tenant ID for multi-tenant isolation.
                       When provided, validates that the entry belongs to
                       the specified tenant before demoting.

        Returns:
            True if the entry was demoted, False if not found or tenant mismatch
        """
        # Validate tenant isolation before demotion
        if tenant_id is not None:
            existing = self.get(memory_id)
            if existing is None:
                return False
            entry_tenant = existing.metadata.get("tenant_id")
            if entry_tenant and entry_tenant != tenant_id:
                logger.warning(
                    "Cross-tenant demotion blocked: memory=%s entry_tenant=%s request_tenant=%s",
                    memory_id,
                    entry_tenant,
                    tenant_id,
                )
                return False

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE continuum_memory
                SET tier = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_tier.value, utc_now_iso_naive(), memory_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def demote_entry_async(
        self: ContinuumMemory,
        memory_id: str,
        new_tier: MemoryTier,
        tenant_id: str | None = None,
    ) -> bool:
        """Async wrapper for demote_entry() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.demote_entry(memory_id, new_tier, tenant_id)
        )


__all__ = ["CrudMixin"]
