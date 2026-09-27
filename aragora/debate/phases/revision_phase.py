"""
Revision phase module for debate rounds.

Handles parallel revision generation with bounded concurrency.
This module is extracted from debate_rounds.py for better modularity.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import (
    AGENT_TIMEOUT_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_CONCURRENT_REVISIONS,
)
from aragora.debate.complexity_governor import get_complexity_governor
from aragora.events.context import streaming_task_context

if TYPE_CHECKING:
    from aragora.core import Agent, Critique, Message
    from aragora.debate.context import DebateContext
    from aragora.debate.molecules import MoleculeTracker

logger = logging.getLogger(__name__)

# Base timeout for the entire revision phase gather (prevents indefinite stalls)
REVISION_PHASE_BASE_TIMEOUT = 120.0


def calculate_phase_timeout(num_agents: int, agent_timeout: float) -> float:
    """Calculate dynamic phase timeout based on agent count.

    Ensures phase timeout exceeds (agents / max_concurrent) * agent_timeout.
    This prevents the phase from timing out before all agents can complete.

    Args:
        num_agents: Number of agents in the phase
        agent_timeout: Per-agent timeout in seconds

    Returns:
        Phase timeout in seconds
    """
    # With bounded concurrency, worst case is sequential execution
    # Add 60s buffer for gather overhead and safety margin
    calculated = (num_agents / MAX_CONCURRENT_REVISIONS) * agent_timeout + 60.0
    return max(calculated, REVISION_PHASE_BASE_TIMEOUT)


class RevisionGenerator:
    """
    Generates revisions in parallel with bounded concurrency.

    This class handles the parallel generation of revised proposals
    from agents based on critiques received, with semaphore-bounded
    concurrency to prevent API rate limit exhaustion.

    Usage:
        generator = RevisionGenerator(
            generate_with_agent=arena._generate_with_agent,
            build_revision_prompt=arena._build_revision_prompt,
            with_timeout=arena._with_timeout,
            circuit_breaker=arena.circuit_breaker,
            hooks=arena.hooks,
            recorder=arena.recorder,
            notify_spectator=arena._notify_spectator,
            heartbeat_callback=arena._emit_heartbeat,
            record_grounded_position=arena._record_grounded_position,
            rhetorical_observer=arena._rhetorical_observer,
        )
        await generator.execute_revision_phase(ctx, round_num, all_critiques, result)
    """

    def __init__(
        self,
        generate_with_agent: Callable | None = None,
        build_revision_prompt: Callable | None = None,
        with_timeout: Callable | None = None,
        circuit_breaker: Any | None = None,
        hooks: dict | None = None,
        recorder: Any | None = None,
        notify_spectator: Callable | None = None,
        heartbeat_callback: Callable | None = None,
        record_grounded_position: Callable | None = None,
        rhetorical_observer: Any | None = None,
        max_concurrent: int = MAX_CONCURRENT_REVISIONS,
        # Molecule tracking for work unit management (Gastown pattern)
        molecule_tracker: MoleculeTracker | None = None,
    ):
        """
        Initialize the revision generator.

        Args:
            generate_with_agent: Async callback for generating content
            build_revision_prompt: Callback to build revision prompt
            with_timeout: Async timeout wrapper callback
            circuit_breaker: Circuit breaker for agent failure tracking
            hooks: Dictionary of event hooks
            recorder: Debate recorder for logging turns
            notify_spectator: Callback for spectator notifications
            heartbeat_callback: Callback for emitting heartbeats
            record_grounded_position: Callback for grounded persona tracking
            rhetorical_observer: Rhetorical observer for pattern detection
            max_concurrent: Maximum concurrent revision generations
            molecule_tracker: Optional MoleculeTracker for work unit tracking
        """
        self._generate_with_agent = generate_with_agent
        self._build_revision_prompt = build_revision_prompt
        self._with_timeout = with_timeout
        self.circuit_breaker = circuit_breaker
        self.hooks = hooks or {}
        self.recorder = recorder
        self._notify_spectator = notify_spectator
        self._emit_heartbeat = heartbeat_callback
        self._record_grounded_position = record_grounded_position
        self._rhetorical_observer = rhetorical_observer
        self._max_concurrent = max_concurrent

        # Molecule tracking for work unit management
        self._molecule_tracker = molecule_tracker
        self._active_molecules: dict[str, str] = {}  # agent_name -> molecule_id

    async def execute_revision_phase(
        self,
        ctx: DebateContext,
        round_num: int,
        all_critiques: list[Critique],
        partial_messages: list[Message],
    ) -> dict[str, str]:
        """
        Execute revision phase with parallel generation.

        Args:
            ctx: The DebateContext with proposals and proposers
            round_num: Current round number
            all_critiques: List of all critiques from this round
            partial_messages: List to append new messages to

        Returns:
            Dict mapping agent name to revised proposal
        """
        from aragora.core import Message

        result = ctx.result
        proposals = ctx.proposals
        updated_proposals: dict[str, str] = {}

        generate_with_agent = self._generate_with_agent
        build_revision_prompt = self._build_revision_prompt
        if generate_with_agent is None or build_revision_prompt is None:
            logger.warning("Missing callbacks for revision phase")
            return updated_proposals

        if not all_critiques:
            return updated_proposals

        # Semaphore for bounded concurrency
        revision_semaphore = asyncio.Semaphore(self._max_concurrent)

        async def generate_revision_bounded(agent: Agent, revision_prompt: str):
            """Wrap revision generation with semaphore for bounded concurrency."""
            base_timeout = getattr(agent, "timeout", AGENT_TIMEOUT_SECONDS)
            timeout = get_complexity_governor().get_scaled_timeout(float(base_timeout))
            task_id = f"{agent.name}:revision:{round_num}"
            async with revision_semaphore:
                # Mark molecule as in_progress
                self._start_molecule(agent.name)
                with streaming_task_context(task_id):
                    with_timeout = self._with_timeout
                    if with_timeout is not None:
                        return await with_timeout(
                            generate_with_agent(agent, revision_prompt, ctx.context_messages),
                            agent.name,
                            timeout_seconds=timeout,
                        )
                    return await generate_with_agent(agent, revision_prompt, ctx.context_messages)

        # Build revision tasks for all proposers
        revision_tasks = []
        revision_agents = []

        for agent in ctx.proposers:
            # Filter critiques specifically targeting this agent
            agent_critiques = [c for c in all_critiques if c.target_agent == agent.name]

            # Skip revision if no critiques for this agent
            if not agent_critiques:
                logger.debug("No critiques targeting %s, skipping revision", agent.name)
                continue

            revision_prompt = build_revision_prompt(
                agent, proposals.get(agent.name, ""), agent_critiques, round_num
            )
            revision_tasks.append(generate_revision_bounded(agent, revision_prompt))
            revision_agents.append(agent)

        # Create molecules for tracking if tracker is available
        debate_id = getattr(ctx, "debate_id", None) or (ctx.env.task[:50] if ctx.env else "unknown")
        self._create_revision_molecules(debate_id, round_num, revision_agents)

        # Calculate dynamic phase timeout using base timeout constant
        base_timeout = AGENT_TIMEOUT_SECONDS
        phase_timeout = calculate_phase_timeout(len(revision_agents), base_timeout)

        # Emit heartbeat before revision phase
        if self._emit_heartbeat:
            self._emit_heartbeat(
                f"revision_round_{round_num}", f"starting_{len(revision_agents)}_agents"
            )

        # Periodic heartbeat task during long-running revisions
        async def heartbeat_during_revisions():
            """Emit heartbeat during revisions to keep connection alive."""
            heartbeat_count = 0
            interval = HEARTBEAT_INTERVAL_SECONDS
            try:
                while True:
                    await asyncio.sleep(interval)
                    heartbeat_count += 1
                    if self._emit_heartbeat:
                        self._emit_heartbeat(
                            f"revision_round_{round_num}",
                            f"in_progress_{heartbeat_count * interval}s",
                        )
            except asyncio.CancelledError:
                pass

        # Execute all revisions with bounded concurrency and phase-level timeout
        heartbeat_task = asyncio.create_task(heartbeat_during_revisions())
        try:
            revision_results = await asyncio.wait_for(
                asyncio.gather(*revision_tasks, return_exceptions=True),
                timeout=phase_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"revision_phase_timeout: phase exceeded {phase_timeout:.0f}s limit, "
                f"agents={[a.name for a in revision_agents]}"
            )
            revision_results = [asyncio.TimeoutError()] * len(revision_tasks)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Process results
        revision_count = 0
        total_revisions = len(revision_agents)

        for agent, revised in zip(revision_agents, revision_results):
            revision_count += 1

            # Emit heartbeat for each completed revision
            if self._emit_heartbeat:
                self._emit_heartbeat(
                    f"revision_round_{round_num}",
                    f"processed_{revision_count}_of_{total_revisions}",
                )

            if isinstance(revised, BaseException):
                logger.error("revision_error agent=%s error=%s", agent.name, revised)
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure(agent.name)
                # Mark molecule as failed
                self._fail_molecule(agent.name, str(revised))
                continue

            # Process successful revision
            revised_str: str = revised
            if self.circuit_breaker:
                self.circuit_breaker.record_success(agent.name)

            proposals[agent.name] = revised_str
            updated_proposals[agent.name] = revised_str
            logger.debug("revision_complete agent=%s length=%s", agent.name, len(revised_str))

            # Notify spectator
            if self._notify_spectator:
                self._notify_spectator(
                    "propose",
                    agent=agent.name,
                    details=f"Revised proposal ({len(revised_str)} chars)",
                    metric=len(revised_str),
                )

            # Create message
            msg = Message(
                role="proposer",
                agent=agent.name,
                content=revised_str,
                round=round_num,
            )
            ctx.add_message(msg)  # also appends to result.messages (#9661)
            partial_messages.append(msg)

            # Emit message event
            if "on_message" in self.hooks:
                self.hooks["on_message"](
                    agent=agent.name,
                    content=revised_str,
                    role="proposer",
                    round_num=round_num,
                )

            # Record revision
            if self.recorder:
                try:
                    self.recorder.record_turn(agent.name, revised_str, round_num)
                except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                    logger.debug("Recorder error for revision: %s", e)

            # Record position for grounded personas
            record_position = self._record_grounded_position
            if record_position is not None:
                debate_id = (
                    result.id
                    if result is not None and hasattr(result, "id")
                    else (ctx.env.task[:50] if ctx.env else "")
                )
                record_position(agent.name, revised_str, debate_id, round_num, 0.75)

            # Observe rhetorical patterns for audience engagement
            loop_id = ctx.loop_id if hasattr(ctx, "loop_id") else ""
            self._observe_rhetorical_patterns(agent.name, revised_str, round_num, loop_id)

            # Mark molecule as completed
            self._complete_molecule(
                agent.name,
                {
                    "chars": len(revised_str),
                    "round": round_num,
                },
            )

        return updated_proposals

    def _observe_rhetorical_patterns(
        self,
        agent: str,
        content: str,
        round_num: int,
        loop_id: str,
    ) -> None:
        """Observe content for rhetorical patterns.

        Args:
            agent: Name of the agent
            content: Content to analyze
            round_num: Current round number
            loop_id: Optional loop ID for tracking
        """
        if not self._rhetorical_observer:
            return

        try:
            # Analyze content for rhetorical patterns
            self._rhetorical_observer.observe(
                agent=agent,
                content=content,
                round=round_num,
                loop_id=loop_id,
            )
        except (RuntimeError, AttributeError, TypeError, ValueError) as e:  # noqa: BLE001
            logger.debug("Rhetorical observation error: %s", e)

    # Molecule tracking methods (Gastown pattern)

    def _create_revision_molecules(
        self,
        debate_id: str,
        round_num: int,
        agents: list[Agent],
    ) -> None:
        """Create revision molecules for all agents.

        Args:
            debate_id: ID of the current debate
            round_num: Current round number
            agents: List of agents generating revisions
        """
        if not self._molecule_tracker:
            return

        try:
            from aragora.debate.molecules import MoleculeType

            for agent in agents:
                molecule = self._molecule_tracker.create_molecule(
                    debate_id=debate_id,
                    molecule_type=MoleculeType.REVISION,
                    round_number=round_num,
                    input_data={"agent": agent.name, "round": round_num},
                )
                self._active_molecules[agent.name] = molecule.molecule_id
                logger.debug(
                    "[molecule] Created revision molecule %s for agent=%s round=%s",
                    molecule.molecule_id,
                    agent.name,
                    round_num,
                )
        except ImportError:
            logger.debug("[molecule] Molecule imports unavailable")
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.debug("[molecule] Failed to create revision molecules: %s", e)

    def _start_molecule(self, agent_name: str) -> None:
        """Mark a revision molecule as in_progress.

        Args:
            agent_name: Name of the agent whose molecule to start
        """
        if not self._molecule_tracker:
            return

        molecule_id = self._active_molecules.get(agent_name)
        if molecule_id:
            try:
                self._molecule_tracker.start_molecule(molecule_id)
                logger.debug("[molecule] Started revision molecule %s", molecule_id)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to start molecule: %s", e)

    def _complete_molecule(self, agent_name: str, output: dict[str, Any]) -> None:
        """Mark a revision molecule as completed.

        Args:
            agent_name: Name of the agent whose molecule to complete
            output: Output data from the revision
        """
        if not self._molecule_tracker:
            return

        molecule_id = self._active_molecules.get(agent_name)
        if molecule_id:
            try:
                self._molecule_tracker.complete_molecule(molecule_id, output)
                logger.debug("[molecule] Completed revision molecule %s", molecule_id)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to complete molecule: %s", e)

    def _fail_molecule(self, agent_name: str, error: str) -> None:
        """Mark a revision molecule as failed.

        Args:
            agent_name: Name of the agent whose molecule failed
            error: Error message
        """
        if not self._molecule_tracker:
            return

        molecule_id = self._active_molecules.get(agent_name)
        if molecule_id:
            try:
                self._molecule_tracker.fail_molecule(molecule_id, error)
                logger.debug("[molecule] Failed revision molecule %s: %s", molecule_id, error)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to record molecule failure: %s", e)
