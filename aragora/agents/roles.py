"""
Hierarchical Agent Roles: Gastown-Inspired Role System.

This module implements a hierarchical agent role system inspired by Gastown's
Mayor/Witness/Polecats/Crew pattern, providing clear role differentiation
and supervision hierarchies.

Key concepts:
- AgentRole: Role classification (MAYOR, WITNESS, POLECAT, CREW)
- RoleCapabilities: Capabilities and permissions per role
- AgentHierarchy: Supervision relationships between agents
- RoleBasedRouter: Route tasks based on agent roles

Roles:
- MAYOR: Coordinator that initiates convoys and distributes work
- WITNESS: Patrol agent that monitors progress and detects stuck agents
- POLECAT: Ephemeral worker for single-task execution
- CREW: Persistent agent for long-lived collaboration

Usage:
    hierarchy = AgentHierarchy()

    # Register agents with roles
    await hierarchy.register_agent("mayor-001", AgentRole.MAYOR)
    await hierarchy.register_agent("worker-001", AgentRole.CREW, supervised_by="mayor-001")

    # Get agents by role
    mayors = await hierarchy.get_agents_by_role(AgentRole.MAYOR)

    # Route task to appropriate role
    router = RoleBasedRouter(hierarchy)
    agent_id = await router.route_task(task)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from aragora.persistence.db_config import get_default_data_dir

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """
    Gastown-inspired agent role hierarchy.

    Each role has specific responsibilities and capabilities:
    - MAYOR: Coordinator, initiates convoys, distributes work
    - WITNESS: Patrol, monitors progress, detects stuck agents
    - POLECAT: Ephemeral, single-task workers, cleaned up after
    - CREW: Persistent, long-lived, context-aware collaborators
    """

    MAYOR = "mayor"
    WITNESS = "witness"
    POLECAT = "polecat"
    CREW = "crew"


class RoleCapability(str, Enum):
    """Capabilities that can be associated with roles."""

    # Mayor capabilities
    CREATE_CONVOY = "create_convoy"
    ASSIGN_WORK = "assign_work"
    COORDINATE = "coordinate"
    APPROVE_MERGE = "approve_merge"

    # Witness capabilities
    MONITOR_AGENTS = "monitor_agents"
    DETECT_STUCK = "detect_stuck"
    TRIGGER_RECOVERY = "trigger_recovery"
    GENERATE_REPORTS = "generate_reports"

    # Worker capabilities (Polecat/Crew)
    EXECUTE_TASK = "execute_task"
    CLAIM_BEAD = "claim_bead"
    CREATE_MR = "create_mr"
    WRITE_CODE = "write_code"

    # Crew-specific capabilities
    MAINTAIN_CONTEXT = "maintain_context"
    COLLABORATE = "collaborate"
    MENTOR = "mentor"


# Default capabilities per role
ROLE_CAPABILITIES: dict[AgentRole, set[RoleCapability]] = {
    AgentRole.MAYOR: {
        RoleCapability.CREATE_CONVOY,
        RoleCapability.ASSIGN_WORK,
        RoleCapability.COORDINATE,
        RoleCapability.APPROVE_MERGE,
        RoleCapability.GENERATE_REPORTS,
    },
    AgentRole.WITNESS: {
        RoleCapability.MONITOR_AGENTS,
        RoleCapability.DETECT_STUCK,
        RoleCapability.TRIGGER_RECOVERY,
        RoleCapability.GENERATE_REPORTS,
    },
    AgentRole.POLECAT: {
        RoleCapability.EXECUTE_TASK,
        RoleCapability.CLAIM_BEAD,
        RoleCapability.CREATE_MR,
        RoleCapability.WRITE_CODE,
    },
    AgentRole.CREW: {
        RoleCapability.EXECUTE_TASK,
        RoleCapability.CLAIM_BEAD,
        RoleCapability.CREATE_MR,
        RoleCapability.WRITE_CODE,
        RoleCapability.MAINTAIN_CONTEXT,
        RoleCapability.COLLABORATE,
        RoleCapability.MENTOR,
    },
}


@dataclass
class RoleAssignment:
    """
    Assignment of a role to an agent.

    Tracks role assignment with supervision hierarchy.
    """

    agent_id: str
    role: AgentRole
    assigned_at: datetime
    supervised_by: str | None = None  # Agent ID of supervisor
    supervises: list[str] = field(default_factory=list)  # Agent IDs supervised
    capabilities: set[RoleCapability] = field(default_factory=set)
    is_ephemeral: bool = False  # True for Polecats
    expires_at: datetime | None = None  # For ephemeral agents
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize capabilities from role if not provided."""
        if not self.capabilities:
            self.capabilities = ROLE_CAPABILITIES.get(self.role, set()).copy()

        # Polecats are always ephemeral
        if self.role == AgentRole.POLECAT:
            self.is_ephemeral = True

    def has_capability(self, capability: RoleCapability) -> bool:
        """Check if agent has a specific capability."""
        return capability in self.capabilities

    def can_supervise(self, other_role: AgentRole) -> bool:
        """Check if this role can supervise another role."""
        # Mayor can supervise all
        if self.role == AgentRole.MAYOR:
            return True
        # Witness can supervise workers
        if self.role == AgentRole.WITNESS:
            return other_role in (AgentRole.POLECAT, AgentRole.CREW)
        # Crew can mentor Polecats
        if self.role == AgentRole.CREW:
            return other_role == AgentRole.POLECAT
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "assigned_at": self.assigned_at.isoformat(),
            "supervised_by": self.supervised_by,
            "supervises": self.supervises,
            "capabilities": [c.value for c in self.capabilities],
            "is_ephemeral": self.is_ephemeral,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleAssignment:
        """Deserialize from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            role=AgentRole(data["role"]),
            assigned_at=datetime.fromisoformat(data["assigned_at"]),
            supervised_by=data.get("supervised_by"),
            supervises=data.get("supervises", []),
            capabilities={RoleCapability(c) for c in data.get("capabilities", [])},
            is_ephemeral=data.get("is_ephemeral", False),
            expires_at=(
                datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            ),
            metadata=data.get("metadata", {}),
        )


class AgentHierarchy:
    """
    Manages agent role assignments and supervision hierarchy.

    Provides methods for:
    - Registering agents with roles
    - Establishing supervision relationships
    - Finding agents by role or capability
    - Spawning ephemeral Polecats
    """

    def __init__(self, hierarchy_dir: Path | None = None):
        """
        Initialize the hierarchy manager.

        Args:
            hierarchy_dir: Directory for persistence
        """
        if hierarchy_dir is not None:
            self.hierarchy_dir = Path(hierarchy_dir)
            self._legacy_hierarchy_file = None
        else:
            self.hierarchy_dir = get_default_data_dir() / "agent_hierarchy"
            self._legacy_hierarchy_file = self._repo_root() / ".agents" / "hierarchy.json"
        self.hierarchy_file = self.hierarchy_dir / "hierarchy.json"
        self._assignments: dict[str, RoleAssignment] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the hierarchy, loading existing assignments."""
        if self._initialized:
            return

        self.hierarchy_dir.mkdir(parents=True, exist_ok=True)
        await self._load_hierarchy()
        self._initialized = True
        logger.info("AgentHierarchy initialized with %s agents", len(self._assignments))

    async def _load_hierarchy(self) -> None:
        """Load hierarchy from file."""
        sources: list[tuple[Path, bool]] = []
        if self.hierarchy_file.exists():
            sources.append((self.hierarchy_file, False))
        if self._legacy_hierarchy_file is not None and self._legacy_hierarchy_file.exists():
            sources.append((self._legacy_hierarchy_file, True))

        if not sources:
            return

        loaded_any = False
        migrated_legacy = False
        legacy_sources: list[Path] = []
        for source, using_legacy_default in sources:
            try:
                assignments = self._read_assignments(source)
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.error("Failed to load hierarchy from %s: %s", source, e)
                continue
            loaded_any = True
            for assignment in assignments:
                if using_legacy_default:
                    self._assignments.setdefault(assignment.agent_id, assignment)
                else:
                    self._assignments[assignment.agent_id] = assignment
            if using_legacy_default:
                migrated_legacy = True
                legacy_sources.append(source)

        if loaded_any and migrated_legacy:
            if await self._save_hierarchy():
                for source in legacy_sources:
                    self._retire_legacy_hierarchy(source)
                    logger.info(
                        "Migrated legacy agent hierarchy from %s to %s",
                        source,
                        self.hierarchy_file,
                    )
            else:
                logger.error(
                    "Skipped retiring legacy agent hierarchy because save failed: %s",
                    ", ".join(str(source) for source in legacy_sources),
                )

    @staticmethod
    def _read_assignments(source: Path) -> list[RoleAssignment]:
        with open(source) as f:
            data = json.load(f)
        return [RoleAssignment.from_dict(item) for item in data.get("assignments", [])]

    async def _save_hierarchy(self) -> bool:
        """Save hierarchy to file."""
        payload = {
            "assignments": [a.to_dict() for a in self._assignments.values()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = ""
        try:
            self.hierarchy_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.hierarchy_dir),
                prefix=f".{self.hierarchy_file.name}.",
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.hierarchy_file)
            return True
        except (OSError, TypeError, ValueError) as e:
            with contextlib.suppress(FileNotFoundError, OSError):
                os.unlink(tmp)
            logger.error("Failed to save hierarchy: %s", e)
            return False

    @staticmethod
    def _repo_root() -> Path:
        module_root = Path(__file__).resolve().parents[2]
        if (module_root / ".git").exists() or (module_root / ".agents").exists():
            return module_root
        for candidate in (Path.cwd(), *Path.cwd().parents):
            if (candidate / ".git").exists() or (candidate / ".agents").exists():
                return candidate
        return module_root

    @staticmethod
    def _retire_legacy_hierarchy(path: Path) -> None:
        retired = path.with_name(f"{path.name}.migrated")
        with contextlib.suppress(OSError):
            os.replace(path, retired)

    async def register_agent(
        self,
        agent_id: str,
        role: AgentRole,
        supervised_by: str | None = None,
        additional_capabilities: set[RoleCapability] | None = None,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> RoleAssignment:
        """
        Register an agent with a role.

        Args:
            agent_id: Unique agent identifier
            role: Role to assign
            supervised_by: Agent ID of supervisor
            additional_capabilities: Extra capabilities beyond role defaults
            metadata: Additional metadata
            expires_at: Optional expiration timestamp for ephemeral agents

        Returns:
            The created role assignment
        """
        async with self._lock:
            previous_assignment = self._assignments.get(agent_id)
            supervisor_before: tuple[str, list[str]] | None = None
            if supervised_by and supervised_by in self._assignments:
                supervisor_before = (
                    supervised_by,
                    list(self._assignments[supervised_by].supervises),
                )

            # Create assignment
            assignment = RoleAssignment(
                agent_id=agent_id,
                role=role,
                assigned_at=datetime.now(timezone.utc),
                supervised_by=supervised_by,
                metadata=metadata or {},
                expires_at=expires_at,
            )

            # Add additional capabilities
            if additional_capabilities:
                assignment.capabilities.update(additional_capabilities)

            # Update supervisor's supervises list
            if supervised_by and supervised_by in self._assignments:
                supervisor = self._assignments[supervised_by]
                if agent_id not in supervisor.supervises:
                    supervisor.supervises.append(agent_id)

            self._assignments[agent_id] = assignment
            if not await self._save_hierarchy():
                if previous_assignment is None:
                    self._assignments.pop(agent_id, None)
                else:
                    self._assignments[agent_id] = previous_assignment
                if supervisor_before is not None:
                    supervisor_id, supervises = supervisor_before
                    rollback_supervisor = self._assignments.get(supervisor_id)
                    if rollback_supervisor is not None:
                        rollback_supervisor.supervises = supervises
                raise RuntimeError("failed to save agent hierarchy after registering agent")

            logger.info("Registered agent %s as %s", agent_id, role.value)
            return assignment

    async def unregister_agent(self, agent_id: str) -> bool:
        """
        Unregister an agent.

        Args:
            agent_id: Agent to unregister

        Returns:
            True if unregistered, False if not found
        """
        async with self._lock:
            if agent_id not in self._assignments:
                return False

            assignment = self._assignments[agent_id]
            supervisor_before: tuple[str, list[str]] | None = None
            if assignment.supervised_by:
                supervisor = self._assignments.get(assignment.supervised_by)
                if supervisor is not None:
                    supervisor_before = (assignment.supervised_by, list(supervisor.supervises))
            supervised_before = {
                supervised_id: self._assignments[supervised_id].supervised_by
                for supervised_id in assignment.supervises
                if supervised_id in self._assignments
            }

            # Remove from supervisor's list
            if assignment.supervised_by:
                supervisor = self._assignments.get(assignment.supervised_by)
                if supervisor and agent_id in supervisor.supervises:
                    supervisor.supervises.remove(agent_id)

            # Reassign supervised agents
            for supervised_id in assignment.supervises:
                supervised = self._assignments.get(supervised_id)
                if supervised:
                    supervised.supervised_by = assignment.supervised_by

            del self._assignments[agent_id]
            if not await self._save_hierarchy():
                self._assignments[agent_id] = assignment
                if supervisor_before is not None:
                    supervisor_id, supervises = supervisor_before
                    supervisor = self._assignments.get(supervisor_id)
                    if supervisor is not None:
                        supervisor.supervises = supervises
                for supervised_id, previous_supervisor in supervised_before.items():
                    supervised = self._assignments.get(supervised_id)
                    if supervised is not None:
                        supervised.supervised_by = previous_supervisor
                raise RuntimeError("failed to save agent hierarchy after unregistering agent")

            logger.info("Unregistered agent %s", agent_id)
            return True

    async def get_assignment(self, agent_id: str) -> RoleAssignment | None:
        """Get role assignment for an agent."""
        return self._assignments.get(agent_id)

    async def get_agents_by_role(self, role: AgentRole) -> list[RoleAssignment]:
        """Get all agents with a specific role."""
        return [a for a in self._assignments.values() if a.role == role]

    async def get_agents_by_capability(self, capability: RoleCapability) -> list[RoleAssignment]:
        """Get all agents with a specific capability."""
        return [a for a in self._assignments.values() if a.has_capability(capability)]

    async def get_supervisor(self, agent_id: str) -> RoleAssignment | None:
        """Get the supervisor of an agent."""
        assignment = self._assignments.get(agent_id)
        if assignment and assignment.supervised_by:
            return self._assignments.get(assignment.supervised_by)
        return None

    async def get_supervised(self, agent_id: str) -> list[RoleAssignment]:
        """Get agents supervised by an agent."""
        assignment = self._assignments.get(agent_id)
        if not assignment:
            return []
        return [self._assignments[sid] for sid in assignment.supervises if sid in self._assignments]

    async def spawn_polecat(
        self,
        supervised_by: str,
        task_description: str,
        ttl_minutes: int = 60,
    ) -> RoleAssignment:
        """
        Spawn an ephemeral Polecat worker.

        Args:
            supervised_by: Supervisor agent ID
            task_description: Description of the task
            ttl_minutes: Time-to-live in minutes

        Returns:
            The Polecat assignment
        """
        from datetime import timedelta

        agent_id = f"polecat-{str(uuid.uuid4())[:8]}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

        assignment = await self.register_agent(
            agent_id=agent_id,
            role=AgentRole.POLECAT,
            supervised_by=supervised_by,
            metadata={"task_description": task_description},
            expires_at=expires_at,
        )
        logger.info("Spawned Polecat %s for task: %s...", agent_id, task_description[:50])
        return assignment

    async def cleanup_expired_polecats(self) -> int:
        """
        Clean up expired Polecat agents.

        Returns:
            Number of agents cleaned up
        """
        now = datetime.now(timezone.utc)
        expired = [
            a.agent_id
            for a in self._assignments.values()
            if a.role == AgentRole.POLECAT and a.expires_at and a.expires_at < now
        ]

        for agent_id in expired:
            await self.unregister_agent(agent_id)

        if expired:
            logger.info("Cleaned up %s expired Polecats", len(expired))
        return len(expired)

    async def get_statistics(self) -> dict[str, Any]:
        """Get statistics about the hierarchy."""
        assignments = list(self._assignments.values())
        by_role: dict[str, int] = {}
        for assignment in assignments:
            by_role[assignment.role.value] = by_role.get(assignment.role.value, 0) + 1

        return {
            "total_agents": len(assignments),
            "by_role": by_role,
            "ephemeral_count": len([a for a in assignments if a.is_ephemeral]),
        }


class RoleBasedRouter:
    """
    Routes tasks to appropriate agents based on roles.

    Uses the agent hierarchy to:
    - Route coordination tasks to Mayor agents
    - Route monitoring tasks to Witness agents
    - Route execution tasks to Crew/Polecat agents
    """

    def __init__(self, hierarchy: AgentHierarchy):
        """
        Initialize the router.

        Args:
            hierarchy: The agent hierarchy to use
        """
        self.hierarchy = hierarchy

    async def route_task(
        self,
        task_type: str,
        required_capabilities: set[RoleCapability] | None = None,
        prefer_persistent: bool = True,
    ) -> str | None:
        """
        Route a task to an appropriate agent.

        Args:
            task_type: Type of task (coordination, monitoring, execution)
            required_capabilities: Required capabilities for the task
            prefer_persistent: Prefer Crew over Polecat for execution tasks

        Returns:
            Agent ID to route to, or None if no suitable agent
        """
        # Determine role based on task type
        if task_type == "coordination":
            target_role = AgentRole.MAYOR
        elif task_type == "monitoring":
            target_role = AgentRole.WITNESS
        elif task_type == "execution":
            target_role = AgentRole.CREW if prefer_persistent else AgentRole.POLECAT
        else:
            # Default to Crew
            target_role = AgentRole.CREW

        # Get agents with target role
        agents = await self.hierarchy.get_agents_by_role(target_role)

        # Filter by required capabilities
        if required_capabilities:
            agents = [a for a in agents if all(a.has_capability(c) for c in required_capabilities)]

        if not agents:
            # Fallback to any capable agent
            if required_capabilities:
                for cap in required_capabilities:
                    agents = await self.hierarchy.get_agents_by_capability(cap)
                    if agents:
                        break

        if not agents:
            return None

        # Return first available (could add load balancing here)
        return agents[0].agent_id

    async def route_to_mayor(self) -> str | None:
        """Get a Mayor agent for coordination."""
        mayors = await self.hierarchy.get_agents_by_role(AgentRole.MAYOR)
        return mayors[0].agent_id if mayors else None

    async def route_to_witness(self) -> str | None:
        """Get a Witness agent for monitoring."""
        witnesses = await self.hierarchy.get_agents_by_role(AgentRole.WITNESS)
        return witnesses[0].agent_id if witnesses else None

    async def spawn_worker_for_task(
        self,
        task_description: str,
        supervised_by: str | None = None,
    ) -> str:
        """
        Spawn an ephemeral worker for a task.

        Args:
            task_description: Description of the task
            supervised_by: Supervisor agent ID (defaults to Mayor)

        Returns:
            Agent ID of the spawned worker
        """
        # Find supervisor
        if not supervised_by:
            supervised_by = await self.route_to_mayor()

        if not supervised_by:
            # No Mayor, use any Witness
            supervised_by = await self.route_to_witness()

        if not supervised_by:
            raise ValueError("No supervisor available to spawn Polecat")

        assignment = await self.hierarchy.spawn_polecat(
            supervised_by=supervised_by,
            task_description=task_description,
        )
        return assignment.agent_id


# Singleton instance
_default_hierarchy: AgentHierarchy | None = None


async def get_agent_hierarchy(hierarchy_dir: Path | None = None) -> AgentHierarchy:
    """Get the default agent hierarchy instance."""
    global _default_hierarchy
    if _default_hierarchy is None:
        _default_hierarchy = AgentHierarchy(hierarchy_dir)
        await _default_hierarchy.initialize()
    return _default_hierarchy


def reset_agent_hierarchy() -> None:
    """Reset the default hierarchy (for testing)."""
    global _default_hierarchy
    _default_hierarchy = None
