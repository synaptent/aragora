"""
Bead Manager - Atomic work units backed by the canonical store.

Beads are the Gastown equivalent of atomic tasks: each bead represents
a single unit of work with a prefix + 5-character ID. Beads are tracked
via the canonical bead store for crash-resilient state management.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from aragora.nomic.stores import (
    Bead as NomicBead,
    BeadStatus as NomicBeadStatus,
    BeadStore as NomicBeadStore,
)
from aragora.nomic.stores.paths import should_use_canonical_store
from aragora.nomic.stores.adapters.workspace import (
    nomic_bead_to_workspace,
    workspace_bead_metadata,
    workspace_bead_status_to_nomic,
    workspace_bead_to_nomic,
    resolve_workspace_bead_status,
)
from aragora.stores.canonical import WorkspaceStores, get_canonical_workspace_stores

logger = logging.getLogger(__name__)


class BeadStatus(Enum):
    """Workspace bead lifecycle status.

    Maps to canonical ``aragora.nomic.stores.BeadStatus``:
        PENDING  -> NomicBeadStatus.PENDING
        ASSIGNED -> NomicBeadStatus.CLAIMED
        RUNNING  -> NomicBeadStatus.RUNNING
        DONE     -> NomicBeadStatus.COMPLETED
        FAILED   -> NomicBeadStatus.FAILED
        SKIPPED  -> NomicBeadStatus.CANCELLED
    """

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    def to_nomic(self) -> NomicBeadStatus:
        """Convert to canonical nomic status."""
        mapping = {
            BeadStatus.PENDING: NomicBeadStatus.PENDING,
            BeadStatus.ASSIGNED: NomicBeadStatus.CLAIMED,
            BeadStatus.RUNNING: NomicBeadStatus.RUNNING,
            BeadStatus.DONE: NomicBeadStatus.COMPLETED,
            BeadStatus.FAILED: NomicBeadStatus.FAILED,
            BeadStatus.SKIPPED: NomicBeadStatus.CANCELLED,
        }
        return mapping[self]

    @classmethod
    def from_nomic(cls, nomic_status: NomicBeadStatus) -> BeadStatus:
        """Convert from canonical nomic status."""
        mapping = {
            NomicBeadStatus.PENDING: cls.PENDING,
            NomicBeadStatus.CLAIMED: cls.ASSIGNED,
            NomicBeadStatus.RUNNING: cls.RUNNING,
            NomicBeadStatus.COMPLETED: cls.DONE,
            NomicBeadStatus.FAILED: cls.FAILED,
            NomicBeadStatus.CANCELLED: cls.SKIPPED,
            NomicBeadStatus.BLOCKED: cls.PENDING,
        }
        return mapping.get(nomic_status, cls.PENDING)


@dataclass
class Bead:
    """An atomic unit of work (Gastown bead equivalent)."""

    bead_id: str  # prefix + 5-char ID
    convoy_id: str
    workspace_id: str
    title: str = ""
    description: str = ""
    status: BeadStatus = BeadStatus.PENDING
    assigned_agent: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    git_ref: str | None = None
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bead:
        """Deserialize from dictionary."""
        data = dict(data)
        if isinstance(data.get("status"), str):
            data["status"] = BeadStatus(data["status"])
        return cls(**data)


def generate_bead_id(prefix: str = "bd") -> str:
    """Generate a bead ID with prefix + 5-char hash (Gastown convention)."""
    h = hashlib.sha256(f"{time.time()}-{id(prefix)}".encode()).hexdigest()[:5]
    return f"{prefix}-{h}"


class BeadManager:
    """
    Manages beads (atomic work units) with canonical persistence.

    Features:
    - Create beads with auto-generated IDs
    - Track bead lifecycle (pending → assigned → running → done/failed)
    - Persist bead state via the canonical bead store for crash recovery
    - List and filter beads by status, convoy, agent
    - Dependency tracking between beads
    """

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        use_nomic_store: bool | None = None,
        nomic_store: NomicBeadStore | None = None,
        canonical_stores: WorkspaceStores | None = None,
    ) -> None:
        self._storage_dir = Path(storage_dir) if storage_dir else None
        default_use = should_use_canonical_store(default=True) or bool(storage_dir)
        self._use_nomic_store = use_nomic_store if use_nomic_store is not None else default_use
        if not self._use_nomic_store:
            logger.warning(
                "Workspace BeadManager fallback store is deprecated; using canonical store."
            )
            self._use_nomic_store = True
        self._nomic_store = nomic_store
        self._canonical_stores = canonical_stores
        self._nomic_initialized = False
        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
        if self._use_nomic_store and self._nomic_store is None:
            if self._canonical_stores is None:
                bead_dir = str(self._storage_dir) if self._storage_dir else None
                self._canonical_stores = get_canonical_workspace_stores(
                    bead_dir=bead_dir,
                    git_enabled=False,
                    auto_commit=False,
                )

    async def _ensure_nomic_store(self) -> NomicBeadStore:
        if self._nomic_store is None:
            if self._canonical_stores is None:
                bead_dir = str(self._storage_dir) if self._storage_dir else None
                self._canonical_stores = get_canonical_workspace_stores(
                    bead_dir=bead_dir,
                    git_enabled=False,
                    auto_commit=False,
                )
            self._nomic_store = await self._canonical_stores.bead_store()
        store = self._nomic_store
        if not self._nomic_initialized:
            await store.initialize()
            self._nomic_initialized = True
        return store

    def _to_nomic_status(self, status: BeadStatus) -> NomicBeadStatus:
        return workspace_bead_status_to_nomic(status)

    def _from_nomic_status(self, status: NomicBeadStatus, metadata: dict[str, Any]) -> BeadStatus:
        return resolve_workspace_bead_status(status, metadata, BeadStatus)

    def _workspace_metadata(self, bead: Bead) -> dict[str, Any]:
        return workspace_bead_metadata(bead)

    def _to_nomic_bead(self, bead: Bead) -> NomicBead:
        return workspace_bead_to_nomic(bead)

    def _from_nomic_bead(self, bead: NomicBead) -> Bead:
        return nomic_bead_to_workspace(bead, bead_cls=Bead, status_cls=BeadStatus)

    async def create_bead(
        self,
        convoy_id: str,
        workspace_id: str,
        title: str = "",
        description: str = "",
        payload: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        prefix: str = "bd",
    ) -> Bead:
        """Create a new bead."""
        bead_id = generate_bead_id(prefix)
        bead = Bead(
            bead_id=bead_id,
            convoy_id=convoy_id,
            workspace_id=workspace_id,
            title=title,
            description=description,
            payload=payload or {},
            depends_on=depends_on or [],
        )
        store = await self._ensure_nomic_store()
        await store.create(self._to_nomic_bead(bead))
        return bead

    async def get_bead(self, bead_id: str) -> Bead | None:
        """Get a bead by ID."""
        store = await self._ensure_nomic_store()
        nomic_bead = await store.get(bead_id)
        return self._from_nomic_bead(nomic_bead) if nomic_bead else None

    async def assign_bead(self, bead_id: str, agent_id: str) -> Bead | None:
        """Assign a bead to an agent."""
        store = await self._ensure_nomic_store()
        success = await store.claim(bead_id, agent_id)
        if not success:
            return None
        nomic_bead = await store.get(bead_id)
        if not nomic_bead:
            return None
        nomic_bead.metadata.update({"workspace_status": BeadStatus.ASSIGNED.value})
        await store.update(nomic_bead)
        return self._from_nomic_bead(nomic_bead)

    async def start_bead(self, bead_id: str) -> Bead | None:
        """Mark a bead as running."""
        store = await self._ensure_nomic_store()
        await store.update_status(bead_id, NomicBeadStatus.RUNNING)
        nomic_bead = await store.get(bead_id)
        if not nomic_bead:
            return None
        nomic_bead.metadata.update(
            {
                "workspace_status": BeadStatus.RUNNING.value,
                "started_at": time.time(),
            }
        )
        await store.update(nomic_bead)
        return self._from_nomic_bead(nomic_bead)

    async def complete_bead(
        self,
        bead_id: str,
        result: dict[str, Any] | None = None,
    ) -> Bead | None:
        """Mark a bead as done with an optional result."""
        store = await self._ensure_nomic_store()
        await store.update_status(bead_id, NomicBeadStatus.COMPLETED)
        nomic_bead = await store.get(bead_id)
        if not nomic_bead:
            return None
        nomic_bead.metadata.update(
            {
                "workspace_status": BeadStatus.DONE.value,
                "result": result,
                "completed_at": time.time(),
            }
        )
        await store.update(nomic_bead)
        return self._from_nomic_bead(nomic_bead)

    async def fail_bead(self, bead_id: str, error: str) -> Bead | None:
        """Mark a bead as failed."""
        store = await self._ensure_nomic_store()
        await store.update_status(bead_id, NomicBeadStatus.FAILED, error_message=error)
        nomic_bead = await store.get(bead_id)
        if not nomic_bead:
            return None
        nomic_bead.metadata.update(
            {
                "workspace_status": BeadStatus.FAILED.value,
                "completed_at": time.time(),
            }
        )
        await store.update(nomic_bead)
        return self._from_nomic_bead(nomic_bead)

    async def list_beads(
        self,
        convoy_id: str | None = None,
        status: BeadStatus | None = None,
        agent_id: str | None = None,
    ) -> list[Bead]:
        """List beads with optional filters."""
        store = await self._ensure_nomic_store()
        beads = await store.list_all()
        results: list[Bead] = []
        for nomic_bead in beads:
            workspace_bead = self._from_nomic_bead(nomic_bead)
            if convoy_id and workspace_bead.convoy_id != convoy_id:
                continue
            if status and workspace_bead.status != status:
                continue
            if agent_id and workspace_bead.assigned_agent != agent_id:
                continue
            results.append(workspace_bead)
        return results

    async def get_ready_beads(self, convoy_id: str) -> list[Bead]:
        """Get beads that are ready to execute (dependencies met)."""
        store = await self._ensure_nomic_store()
        ready = await store.list_pending_runnable()
        results: list[Bead] = []
        for nomic_bead in ready:
            workspace_bead = self._from_nomic_bead(nomic_bead)
            if workspace_bead.convoy_id == convoy_id:
                results.append(workspace_bead)
        return results
