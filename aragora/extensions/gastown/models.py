"""
Gastown Extension Data Models.

Defines the core data structures for developer workspace orchestration.

CANONICAL SOURCE: aragora.nomic.stores
Gastown provides a domain-specific view of work tracking with its own
status lifecycle. All persistence delegates to the canonical nomic stores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal
import logging

from aragora.worktree.hook_runner import Hook as Hook, HookType as HookType

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from aragora.nomic.stores import ConvoyStatus as NomicConvoyStatus


class ConvoyStatus(Enum):
    """Gastown convoy lifecycle status.

    CANONICAL SOURCE: aragora.nomic.stores.ConvoyStatus

    Gastown uses a domain-specific lifecycle for developer workflows:
        PENDING     -> NomicConvoyStatus.PENDING
        IN_PROGRESS -> NomicConvoyStatus.ACTIVE
        BLOCKED     -> NomicConvoyStatus.FAILED
        REVIEW      -> NomicConvoyStatus.ACTIVE (with metadata marker)
        COMPLETED   -> NomicConvoyStatus.COMPLETED
        CANCELLED   -> NomicConvoyStatus.CANCELLED

    Workspace layer (aragora.workspace.convoy) has different sub-states:
        CREATED/ASSIGNING/EXECUTING/MERGING/DONE/FAILED/CANCELLED

    Use conversion methods for cross-layer interoperability.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    def to_nomic(self) -> NomicConvoyStatus:
        """Convert to canonical nomic status."""
        from aragora.nomic.stores import ConvoyStatus as NomicConvoyStatus

        mapping = {
            ConvoyStatus.PENDING: NomicConvoyStatus.PENDING,
            ConvoyStatus.IN_PROGRESS: NomicConvoyStatus.ACTIVE,
            ConvoyStatus.BLOCKED: NomicConvoyStatus.FAILED,
            ConvoyStatus.REVIEW: NomicConvoyStatus.ACTIVE,
            ConvoyStatus.COMPLETED: NomicConvoyStatus.COMPLETED,
            ConvoyStatus.CANCELLED: NomicConvoyStatus.CANCELLED,
        }
        return mapping[self]

    @classmethod
    def from_nomic(
        cls,
        nomic_status: NomicConvoyStatus,
        gastown_status: str | None = None,
    ) -> ConvoyStatus:
        """Convert from canonical nomic status.

        If gastown_status is provided (from metadata), use that for
        finer-grained status like BLOCKED vs REVIEW.
        """
        from aragora.nomic.stores import ConvoyStatus as NomicConvoyStatus

        if gastown_status:
            try:
                return cls(gastown_status)
            except ValueError as e:
                logger.debug("from nomic encountered an error: %s", e)
        mapping = {
            NomicConvoyStatus.PENDING: cls.PENDING,
            NomicConvoyStatus.ACTIVE: cls.IN_PROGRESS,
            NomicConvoyStatus.COMPLETED: cls.COMPLETED,
            NomicConvoyStatus.FAILED: cls.BLOCKED,
            NomicConvoyStatus.CANCELLED: cls.CANCELLED,
            NomicConvoyStatus.PARTIAL: cls.IN_PROGRESS,
        }
        return mapping.get(nomic_status, cls.PENDING)

    def to_workspace_status(self) -> str:
        """Map gastown status to workspace ConvoyStatus value.

        Returns the *value* string so callers can construct the workspace
        enum without importing it directly, avoiding circular imports.
        """
        return {
            ConvoyStatus.PENDING: "created",
            ConvoyStatus.IN_PROGRESS: "executing",
            ConvoyStatus.BLOCKED: "failed",
            ConvoyStatus.REVIEW: "merging",
            ConvoyStatus.COMPLETED: "done",
            ConvoyStatus.CANCELLED: "cancelled",
        }[self]

    @classmethod
    def from_workspace_status(cls, value: str) -> ConvoyStatus:
        """Map a workspace ConvoyStatus value string to gastown status."""
        return {
            "created": cls.PENDING,
            "assigning": cls.PENDING,
            "executing": cls.IN_PROGRESS,
            "merging": cls.REVIEW,
            "done": cls.COMPLETED,
            "failed": cls.BLOCKED,
            "cancelled": cls.CANCELLED,
        }.get(value, cls.PENDING)


@dataclass
class WorkspaceConfig:
    """Configuration for a workspace."""

    name: str
    root_path: str
    description: str = ""
    max_rigs: int = 10
    max_agents_per_rig: int = 5
    default_model: str = "claude-3-opus"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Workspace:
    """
    Root container for projects and agents.

    A workspace manages multiple rigs (repository contexts) and coordinates
    agent work across them.
    """

    id: str
    config: WorkspaceConfig
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    owner_id: str = ""
    tenant_id: str | None = None
    status: Literal["active", "archived", "suspended"] = "active"
    rigs: list[str] = field(default_factory=list)  # Rig IDs
    active_convoys: int = 0


@dataclass
class RigConfig:
    """Configuration for a rig (repository context)."""

    name: str
    repo_path: str
    branch: str = "main"
    worktree_path: str | None = None
    description: str = ""
    max_agents: int = 5
    tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Rig:
    """
    Per-repository container with agent context.

    A rig represents a specific repository or worktree where agents can
    operate. It maintains context about the codebase and active work.
    """

    id: str
    workspace_id: str
    config: RigConfig
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["active", "paused", "archived"] = "active"
    agents: list[str] = field(default_factory=list)  # Agent IDs
    active_convoys: list[str] = field(default_factory=list)  # Convoy IDs
    last_sync: datetime | None = None


@dataclass
class ConvoyArtifact:
    """An artifact produced by a convoy."""

    id: str
    convoy_id: str
    type: str  # "file", "diff", "log", "report", "receipt"
    path: str
    content_hash: str = ""
    size_bytes: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Convoy:
    """
    Work tracking unit with artifacts and handoffs.

    A convoy represents a unit of work that flows through the system,
    collecting artifacts and tracking state across agent handoffs.
    """

    id: str
    rig_id: str
    title: str
    description: str = ""
    status: ConvoyStatus = ConvoyStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Task tracking
    issue_ref: str | None = None  # External issue reference
    parent_convoy: str | None = None  # For sub-tasks
    depends_on: list[str] = field(default_factory=list)

    # Agent assignment
    assigned_agents: list[str] = field(default_factory=list)
    current_agent: str | None = None
    handoff_count: int = 0

    # Artifacts and results
    artifacts: list[str] = field(default_factory=list)  # Artifact IDs
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    # Metadata
    priority: int = 0  # Higher = more important
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ConvoyRecord protocol properties (cross-layer compatibility)
    @property
    def convoy_id(self) -> str:
        """Protocol: convoy identifier."""
        return self.id

    @property
    def convoy_title(self) -> str:
        """Protocol: convoy title."""
        return self.title

    @property
    def convoy_description(self) -> str:
        """Protocol: convoy description."""
        return self.description

    @property
    def convoy_bead_ids(self) -> list[str]:
        """Protocol: bead IDs (gastown tracks artifacts, not beads)."""
        return []  # Gastown doesn't track beads directly

    @property
    def convoy_status_value(self) -> str:
        """Protocol: status enum value."""
        return self.status.value

    @property
    def convoy_created_at(self) -> datetime:
        """Protocol: creation timestamp."""
        return self.created_at

    @property
    def convoy_updated_at(self) -> datetime:
        """Protocol: last update timestamp."""
        return self.updated_at

    @property
    def convoy_assigned_agents(self) -> list[str]:
        """Protocol: assigned agent IDs."""
        return self.assigned_agents

    @property
    def convoy_error(self) -> str | None:
        """Protocol: error message if failed."""
        return self.error

    @property
    def convoy_metadata(self) -> dict[str, Any]:
        """Protocol: metadata dictionary."""
        return self.metadata


@dataclass
class LedgerEntry:
    """
    Entry in the work ledger (Beads-style issue tracking).

    Tracks issues, tasks, and decisions with full provenance.
    """

    id: str
    workspace_id: str
    type: Literal["issue", "task", "decision", "note"]
    title: str
    body: str = ""
    status: Literal["open", "in_progress", "resolved", "closed"] = "open"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None

    # Relationships
    convoy_id: str | None = None
    parent_id: str | None = None
    related_entries: list[str] = field(default_factory=list)

    # Attribution
    created_by: str = ""  # Agent or user ID
    assigned_to: list[str] = field(default_factory=list)

    # Labels and metadata
    labels: list[str] = field(default_factory=list)
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
