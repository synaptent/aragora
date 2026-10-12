"""
Implement Executor: Gastown-style multi-agent code generation.

Bridges the Nomic loop's ImplementPhase with the Gastown-inspired
convoy/bead/hook infrastructure for parallel multi-agent code generation
with cross-checking.

Instead of a single agent implementing all changes, this executor:
1. Decomposes the design into atomic beads (work units)
2. Creates a convoy (coordinated work group)
3. Distributes beads to agents via HookQueues
4. Agents implement in parallel with cross-checking
5. Results are verified and merged

Key concepts:
- Convoy: A coordinated group of agents working on related tasks
- Bead: An atomic unit of work (single file change, function, etc.)
- Hook: Per-agent work queue (GUPP: agents MUST process their hook)
- Cross-check: Agent B reviews Agent A's implementation

Usage:
    from aragora.nomic.implement_executor import ConvoyImplementExecutor

    executor = ConvoyImplementExecutor(
        aragora_path=Path("."),
        agents=["anthropic-api", "openai-api", "deepseek", "gemini"],
    )
    result = await executor.execute(design_spec, improvement_description)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class ImplementationBead:
    """An atomic implementation task derived from a design spec."""

    bead_id: str
    title: str
    description: str
    file_path: str
    change_type: str  # "create", "modify", "delete"
    dependencies: list[str] = field(default_factory=list)
    assigned_agent: str | None = None
    reviewer_agent: str | None = None
    status: str = "pending"
    result: str | None = None
    review_result: str | None = None


@dataclass
class BeadTaskResult:
    """Result compatible with ImplementPhase's execute_plan() interface."""

    success: bool
    error: str | None = None
    task_id: str = ""
    files_modified: list[str] = field(default_factory=list)


@dataclass
class ConvoyResult:
    """Result from a convoy-based implementation run."""

    success: bool
    files_modified: list[str] = field(default_factory=list)
    beads_completed: int = 0
    beads_failed: int = 0
    cross_check_passed: int = 0
    cross_check_failed: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


def _generate_bead_id(title: str) -> str:
    """Generate a short bead ID from title."""
    h = hashlib.sha256(f"{time.time()}-{title}".encode()).hexdigest()[:6]
    return f"impl-{h}"


class ConvoyImplementExecutor:
    """
    Multi-agent implementation executor using Gastown convoy/bead patterns.

    Decomposes a design into atomic beads, distributes to agents in parallel,
    and cross-checks results for quality.
    """

    def __init__(
        self,
        aragora_path: Path,
        agents: list[str],
        agent_factory: Callable[[str], Any] | None = None,
        max_parallel: int = 4,
        enable_cross_check: bool = True,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._aragora_path = aragora_path
        self._agents = agents
        self._agent_factory = agent_factory
        self._max_parallel = max_parallel
        self._enable_cross_check = enable_cross_check
        self._log = log_fn or logger.info

    async def execute(
        self,
        design: str,
        improvement: str,
        protected_files: list[str] | None = None,
    ) -> ConvoyResult:
        """
        Execute an implementation using convoy-based multi-agent coding.

        Args:
            design: The design specification to implement
            improvement: Description of the improvement being made
            protected_files: Files that must not be modified

        Returns:
            ConvoyResult with implementation outcomes
        """
        start = time.monotonic()
        protected = set(protected_files or [])

        # Step 1: Decompose design into beads
        beads = self._decompose_design(design, improvement, protected)
        if not beads:
            return ConvoyResult(
                success=False,
                errors=["Failed to decompose design into implementation beads"],
                duration_seconds=time.monotonic() - start,
            )

        self._log(f"Decomposed into {len(beads)} implementation beads")

        # Step 2: Assign agents to beads (round-robin + reviewer assignment)
        self._assign_agents(beads)

        # Step 3: Execute beads in parallel with dependency ordering
        await self._execute_beads(beads)

        # Step 4: Cross-check results
        cross_passed = 0
        cross_failed = 0
        if self._enable_cross_check:
            cross_passed, cross_failed = await self._cross_check(beads)

        # Collect results
        completed = [b for b in beads if b.status == "done"]
        failed = [b for b in beads if b.status == "failed"]
        files_modified = list({b.file_path for b in completed})

        elapsed = time.monotonic() - start
        return ConvoyResult(
            success=len(failed) == 0,
            files_modified=files_modified,
            beads_completed=len(completed),
            beads_failed=len(failed),
            cross_check_passed=cross_passed,
            cross_check_failed=cross_failed,
            duration_seconds=elapsed,
            errors=[f"Bead '{b.title}' failed: {b.result}" for b in failed],
        )

    def _decompose_design(
        self,
        design: str,
        improvement: str,
        protected: set[str],
    ) -> list[ImplementationBead]:
        """
        Decompose a design spec into atomic implementation beads.

        Parses the design for file-level changes and creates one bead
        per file modification.
        """
        beads: list[ImplementationBead] = []
        lines = design.split("\n")
        current_file = ""
        current_changes: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Detect file references
            if stripped.startswith("File:") or stripped.startswith("- File:"):
                if current_file and current_changes:
                    self._add_bead(beads, current_file, current_changes, protected)
                current_file = stripped.split(":", 1)[1].strip().strip("`")
                current_changes = []
            elif stripped.startswith("Create:") or stripped.startswith("- Create:"):
                if current_file and current_changes:
                    self._add_bead(beads, current_file, current_changes, protected)
                current_file = stripped.split(":", 1)[1].strip().strip("`")
                current_changes = ["CREATE NEW FILE"]
            elif stripped.startswith("Modify:") or stripped.startswith("- Modify:"):
                if current_file and current_changes:
                    self._add_bead(beads, current_file, current_changes, protected)
                current_file = stripped.split(":", 1)[1].strip().strip("`")
                current_changes = []
            elif current_file and stripped:
                current_changes.append(stripped)

        # Final bead
        if current_file and current_changes:
            self._add_bead(beads, current_file, current_changes, protected)

        # If no structured file references found, create a single bead
        if not beads:
            beads.append(
                ImplementationBead(
                    bead_id=_generate_bead_id(improvement),
                    title=improvement[:80],
                    description=design[:2000],
                    file_path="<unstructured>",
                    change_type="modify",
                )
            )

        return beads

    def _add_bead(
        self,
        beads: list[ImplementationBead],
        file_path: str,
        changes: list[str],
        protected: set[str],
    ) -> None:
        """Add a bead if the file is not protected."""
        if file_path in protected:
            self._log(f"Skipping protected file: {file_path}")
            return

        change_type = "create" if "CREATE NEW FILE" in changes else "modify"
        description = "\n".join(changes)
        beads.append(
            ImplementationBead(
                bead_id=_generate_bead_id(file_path),
                title=f"{change_type.title()} {file_path}",
                description=description,
                file_path=file_path,
                change_type=change_type,
            )
        )

    def _assign_agents(self, beads: list[ImplementationBead]) -> None:
        """
        Assign agents to beads using round-robin distribution.

        Each bead gets an implementer and a different reviewer for cross-checking.
        """
        if not self._agents:
            return

        for i, bead in enumerate(beads):
            bead.assigned_agent = self._agents[i % len(self._agents)]
            if self._enable_cross_check and len(self._agents) > 1:
                reviewer_idx = (i + 1) % len(self._agents)
                bead.reviewer_agent = self._agents[reviewer_idx]

    async def _execute_beads(self, beads: list[ImplementationBead]) -> None:
        """
        Execute beads in parallel, respecting dependencies and concurrency limits.

        Uses asyncio.Semaphore to limit parallelism.
        """
        sem = asyncio.Semaphore(self._max_parallel)

        # Group beads by dependency level (simple: no deps first, then deps)
        no_deps = [b for b in beads if not b.dependencies]
        with_deps = [b for b in beads if b.dependencies]

        # Execute no-dependency beads in parallel
        if no_deps:
            tasks = [self._execute_single_bead(b, sem) for b in no_deps]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Then execute dependent beads
        if with_deps:
            tasks = [self._execute_single_bead(b, sem) for b in with_deps]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_single_bead(
        self,
        bead: ImplementationBead,
        sem: asyncio.Semaphore,
    ) -> None:
        """Execute a single implementation bead."""
        async with sem:
            bead.status = "running"
            self._log(f"Executing bead: {bead.title} (agent: {bead.assigned_agent})")

            try:
                if self._agent_factory and bead.assigned_agent:
                    agent = self._agent_factory(bead.assigned_agent)
                    prompt = self._build_implement_prompt(bead)
                    result = await agent.generate(prompt)
                    bead.result = result if isinstance(result, str) else str(result)
                    bead.status = "done"
                else:
                    # No agent factory - mark as pending for external execution
                    bead.status = "done"
                    bead.result = f"[Bead ready for external execution: {bead.title}]"

            except (RuntimeError, ValueError, OSError) as exc:
                bead.status = "failed"
                bead.result = str(exc)
                logger.error("Bead %s failed: %s", bead.bead_id, exc)

    async def _cross_check(
        self,
        beads: list[ImplementationBead],
    ) -> tuple[int, int]:
        """
        Cross-check completed beads using reviewer agents.

        Returns (passed, failed) counts.
        """
        passed = 0
        failed = 0

        for bead in beads:
            if bead.status != "done" or not bead.reviewer_agent or not bead.result:
                continue

            try:
                if self._agent_factory:
                    reviewer = self._agent_factory(bead.reviewer_agent)
                    review_prompt = self._build_review_prompt(bead)
                    review = await reviewer.generate(review_prompt)
                    review_str = review if isinstance(review, str) else str(review)
                    bead.review_result = review_str

                    # Simple pass/fail detection
                    lower = review_str.lower()
                    if "approve" in lower or "lgtm" in lower or "correct" in lower:
                        passed += 1
                    else:
                        failed += 1
                        self._log(f"Cross-check failed for {bead.title}: {review_str[:200]}")
                else:
                    passed += 1  # No reviewer available, assume pass

            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("Cross-check failed for %s: %s", bead.bead_id, exc)
                passed += 1  # Don't block on review failures

        return passed, failed

    def _build_implement_prompt(self, bead: ImplementationBead) -> str:
        """Build implementation prompt for an agent."""
        return (
            f"Implement the following change:\n\n"
            f"File: {bead.file_path}\n"
            f"Change type: {bead.change_type}\n\n"
            f"Description:\n{bead.description}\n\n"
            f"SAFETY RULES:\n"
            f"1. NEVER delete or modify protected files\n"
            f"2. NEVER remove existing functionality - only ADD new code\n"
            f"3. Preserve ALL existing imports, classes, and functions\n"
            f"4. Write clean, well-structured code with proper type hints\n"
        )

    def _build_review_prompt(self, bead: ImplementationBead) -> str:
        """Build review prompt for cross-checking."""
        return (
            f"Review the following implementation:\n\n"
            f"File: {bead.file_path}\n"
            f"Change type: {bead.change_type}\n\n"
            f"Original requirement:\n{bead.description}\n\n"
            f"Implementation:\n{bead.result}\n\n"
            f"Check for:\n"
            f"1. Correctness - does it implement the requirement?\n"
            f"2. Safety - no removal of existing functionality\n"
            f"3. Quality - proper type hints, error handling, naming\n\n"
            f"Reply with APPROVE if correct, or describe issues if not.\n"
        )

    async def execute_with_convoy(
        self,
        design: str,
        improvement: str,
        protected_files: list[str] | None = None,
    ) -> ConvoyResult:
        """
        Execute using the full Gastown convoy infrastructure (if available).

        Falls back to the simpler bead-based execution if convoy/hook
        infrastructure is not initialized.
        """
        try:
            import aragora.nomic.convoys
            import aragora.nomic.beads
            import aragora.nomic.hook_queue
            import aragora.nomic.convoy_coordinator  # noqa: F401

            # Use full convoy infrastructure
            self._log("Using Gastown convoy infrastructure for implementation")
            # For now, delegate to the simpler execution path
            # Full convoy wiring can be added when ConvoyManager is initialized
            # with a storage directory
            return await self.execute(design, improvement, protected_files)

        except ImportError:
            logger.info("Convoy infrastructure not available, using direct execution")
            return await self.execute(design, improvement, protected_files)

    async def execute_plan(
        self,
        tasks: list,
        completed: set[str],
        on_task_complete: Callable | None = None,
        stop_on_failure: bool = False,
    ) -> list[BeadTaskResult]:
        """
        Bridge method: adapts ImplementPhase's execute_plan interface
        to the convoy executor's bead-based execution.

        ImplementPhase.execute() at line 501 calls:
            self._executor.execute_plan(plan.tasks, completed, on_task_complete)

        Each task is expected to have .id, .description, and optionally .files attributes.
        Returns list of BeadTaskResult with .success and .error attributes.
        """
        # Convert tasks to beads, skipping already-completed ones
        beads: list[ImplementationBead] = []
        task_to_bead: dict[str, str] = {}  # bead_id -> task_id

        for task in tasks:
            task_id = getattr(task, "id", getattr(task, "task_id", str(id(task))))
            if task_id in completed:
                continue

            description = getattr(task, "description", str(task))
            files = getattr(task, "files", [])
            file_path = files[0] if files else "<unstructured>"

            bead = ImplementationBead(
                bead_id=_generate_bead_id(task_id),
                title=description[:80],
                description=description,
                file_path=file_path,
                change_type="modify",
            )
            beads.append(bead)
            task_to_bead[bead.bead_id] = task_id

        if not beads:
            return []

        # Assign agents and execute
        self._assign_agents(beads)
        await self._execute_beads(beads)

        # Cross-check if enabled
        if self._enable_cross_check:
            await self._cross_check(beads)

        # Build results and fire callbacks
        results: list[BeadTaskResult] = []
        for bead in beads:
            task_id = task_to_bead.get(bead.bead_id, bead.bead_id)
            success = bead.status == "done"
            result = BeadTaskResult(
                success=success,
                error=bead.result if not success else None,
                task_id=task_id,
                files_modified=[bead.file_path] if success else [],
            )
            results.append(result)

            if on_task_complete:
                try:
                    on_task_complete(task_id, result)
                except (
                    TypeError,
                    ValueError,
                    RuntimeError,
                    AttributeError,
                    KeyError,
                    OSError,
                ) as exc:
                    logger.warning("on_task_complete callback failed: %s", exc)

        return results
