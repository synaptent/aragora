"""
Verification phase components.

This module contains components for dependency validation and deadlock detection:
- DependencyGraph: Validates step dependencies and detects cycles
- ResourceLock: Represents a resource lock held by a molecule
- DeadlockDetector: Detects deadlocks between parallel molecule executions
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from aragora.nomic.molecules.base import CyclicDependencyError, DeadlockError

if TYPE_CHECKING:
    from aragora.nomic.molecules.base import MoleculeStep

logger = logging.getLogger(__name__)


# =============================================================================
# Transaction Safety - Dependency Graph Validation
# =============================================================================


class DependencyGraph:
    """
    Validates step dependencies and detects cycles.

    Uses Kahn's algorithm for topological sorting and cycle detection.
    """

    def __init__(self, steps: list[MoleculeStep]):
        self.steps = {s.id: s for s in steps}
        self.adjacency: dict[str, list[str]] = defaultdict(list)
        self.in_degree: dict[str, int] = defaultdict(int)
        self._build_graph()

    def _build_graph(self) -> None:
        """Build adjacency list and in-degree map from steps."""
        for step in self.steps.values():
            # Ensure all steps have an entry
            if step.id not in self.in_degree:
                self.in_degree[step.id] = 0

            for dep_id in step.dependencies:
                self.adjacency[dep_id].append(step.id)
                self.in_degree[step.id] += 1

    def validate(self) -> tuple[bool, list[str] | None]:
        """
        Validate the dependency graph.

        Returns:
            Tuple of (is_valid, error_details)
            - If valid: (True, None)
            - If invalid: (False, list of step IDs forming cycle or missing)
        """
        # Check for missing dependencies
        missing = self._find_missing_dependencies()
        if missing:
            return False, missing

        # Check for cycles
        cycle = self._detect_cycle()
        if cycle:
            return False, cycle

        return True, None

    def _find_missing_dependencies(self) -> list[str] | None:
        """Find any missing dependency references."""
        missing = []
        for step in self.steps.values():
            for dep_id in step.dependencies:
                if dep_id not in self.steps:
                    missing.append(f"{step.id}:{dep_id}")
        return missing if missing else None

    def _detect_cycle(self) -> list[str] | None:
        """
        Detect cycles using DFS with coloring.

        Returns list of step IDs forming the cycle, or None if no cycle.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(self.steps, WHITE)
        parent: dict[str, str | None] = dict.fromkeys(self.steps)

        def dfs(node: str) -> list[str] | None:
            color[node] = GRAY

            for neighbor in self.adjacency[node]:
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # Found a cycle - reconstruct it
                    cycle = [neighbor, node]
                    current = parent[node]
                    while current and current != neighbor:
                        cycle.append(current)
                        current = parent[current]
                    cycle.append(neighbor)
                    return list(reversed(cycle))
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = dfs(neighbor)
                    if result:
                        return result

            color[node] = BLACK
            return None

        for step_id in self.steps:
            if color[step_id] == WHITE:
                result = dfs(step_id)
                if result:
                    return result

        return None

    def get_execution_order(self) -> list[str]:
        """
        Get topologically sorted execution order.

        Returns list of step IDs in valid execution order.
        Raises CyclicDependencyError if cycle exists.
        """
        in_degree = dict(self.in_degree)
        queue = [step_id for step_id, degree in in_degree.items() if degree == 0]
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)

            for neighbor in self.adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self.steps):
            # Cycle detected
            remaining = [s for s in self.steps if s not in order]
            raise CyclicDependencyError(remaining, "Could not complete topological sort")

        return order


# =============================================================================
# Transaction Safety - Deadlock Detection
# =============================================================================


class ResourceLock:
    """Represents a resource lock held by a molecule."""

    def __init__(self, resource_id: str, molecule_id: str, acquired_at: datetime):
        self.resource_id = resource_id
        self.molecule_id = molecule_id
        self.acquired_at = acquired_at


class DeadlockDetector:
    """
    Detects deadlocks between parallel molecule executions.

    Uses wait-for graph analysis to detect cycles indicating deadlocks.
    """

    def __init__(self):
        self._locks: dict[str, ResourceLock] = {}  # resource_id -> lock
        self._waiting: dict[str, set[str]] = defaultdict(
            set
        )  # molecule_id -> waiting_for_resources
        self._holding: dict[str, set[str]] = defaultdict(set)  # molecule_id -> held_resources
        self._lock = asyncio.Lock()

    async def acquire_lock(
        self,
        molecule_id: str,
        resource_id: str,
        timeout: float = 30.0,
    ) -> bool:
        """
        Attempt to acquire a lock on a resource.

        Args:
            molecule_id: ID of the molecule requesting the lock
            resource_id: ID of the resource to lock
            timeout: Maximum time to wait for lock

        Returns:
            True if lock acquired, False if timeout or deadlock detected
        """
        async with self._lock:
            # Check if resource is available
            if resource_id not in self._locks:
                self._locks[resource_id] = ResourceLock(
                    resource_id, molecule_id, datetime.now(timezone.utc)
                )
                self._holding[molecule_id].add(resource_id)
                return True

            # Resource is locked - check for potential deadlock
            holder_id = self._locks[resource_id].molecule_id
            if holder_id == molecule_id:
                return True  # Already own the lock

            # Add to waiting set
            self._waiting[molecule_id].add(resource_id)

            # Check for deadlock
            if self._detect_deadlock_cycle(molecule_id):
                self._waiting[molecule_id].discard(resource_id)
                raise DeadlockError(
                    molecules=[molecule_id, holder_id],
                    resources=[resource_id],
                )

        # Wait for lock with timeout
        start_time = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start_time < timeout:
            await asyncio.sleep(0.1)
            async with self._lock:
                if resource_id not in self._locks:
                    self._locks[resource_id] = ResourceLock(
                        resource_id, molecule_id, datetime.now(timezone.utc)
                    )
                    self._holding[molecule_id].add(resource_id)
                    self._waiting[molecule_id].discard(resource_id)
                    return True

        async with self._lock:
            self._waiting[molecule_id].discard(resource_id)
        return False

    async def release_lock(self, molecule_id: str, resource_id: str) -> None:
        """Release a lock on a resource."""
        async with self._lock:
            if resource_id in self._locks and self._locks[resource_id].molecule_id == molecule_id:
                del self._locks[resource_id]
                self._holding[molecule_id].discard(resource_id)

    async def release_all_locks(self, molecule_id: str) -> None:
        """Release all locks held by a molecule."""
        async with self._lock:
            resources_to_release = list(self._holding.get(molecule_id, set()))
            for resource_id in resources_to_release:
                if resource_id in self._locks:
                    del self._locks[resource_id]
            self._holding[molecule_id].clear()
            self._waiting[molecule_id].clear()

    def _detect_deadlock_cycle(self, start_molecule: str) -> bool:
        """
        Detect if adding this wait would create a deadlock cycle.

        Uses DFS to find cycles in the wait-for graph.
        """
        visited = set()
        path = set()

        def dfs(molecule_id: str) -> bool:
            if molecule_id in path:
                return True  # Cycle found
            if molecule_id in visited:
                return False

            visited.add(molecule_id)
            path.add(molecule_id)

            # Find molecules that this one is waiting for
            for resource_id in self._waiting.get(molecule_id, set()):
                if resource_id in self._locks:
                    holder_id = self._locks[resource_id].molecule_id
                    if dfs(holder_id):
                        return True

            path.remove(molecule_id)
            return False

        return dfs(start_molecule)

    async def get_lock_state(self) -> dict[str, Any]:
        """Get current lock state for debugging."""
        async with self._lock:
            return {
                "locks": {
                    r: {
                        "molecule": lock.molecule_id,
                        "acquired_at": lock.acquired_at.isoformat(),
                    }
                    for r, lock in self._locks.items()
                },
                "waiting": {m: list(w) for m, w in self._waiting.items() if w},
                "holding": {m: list(h) for m, h in self._holding.items() if h},
            }


# Global deadlock detector instance
_deadlock_detector: DeadlockDetector | None = None


def get_deadlock_detector() -> DeadlockDetector:
    """Get the global deadlock detector instance."""
    global _deadlock_detector
    if _deadlock_detector is None:
        _deadlock_detector = DeadlockDetector()
    return _deadlock_detector


def reset_deadlock_detector() -> None:
    """Reset the global deadlock detector (for testing)."""
    global _deadlock_detector
    _deadlock_detector = None
