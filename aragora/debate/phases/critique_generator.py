"""
Critique generation module for debate rounds.

Handles parallel critique generation with bounded concurrency.
This module is extracted from debate_rounds.py for better modularity.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import AGENT_TIMEOUT_SECONDS, MAX_CONCURRENT_CRITIQUES
from aragora.debate.complexity_governor import get_complexity_governor
from aragora.events.context import streaming_task_context

if TYPE_CHECKING:
    from aragora.core import Agent, Critique, Message
    from aragora.debate.context import DebateContext
    from aragora.debate.molecules import MoleculeTracker

logger = logging.getLogger(__name__)


@dataclass
class CritiqueResult:
    """Result of a single critique generation attempt."""

    critic: Agent
    target_agent: str
    critique: Critique | None
    error: Exception | None

    @property
    def success(self) -> bool:
        """True if critique was generated successfully."""
        return self.critique is not None and self.error is None


def _is_effectively_empty_critique(critique: Critique) -> bool:
    """Return True if critique only contains placeholder/empty content."""
    issues = [i.strip() for i in critique.issues if isinstance(i, str) and i.strip()]
    suggestions = [s.strip() for s in critique.suggestions if isinstance(s, str) and s.strip()]
    if not issues and not suggestions:
        return True
    if len(issues) == 1:
        normalized = issues[0].strip().lower()
        if normalized in (
            "agent response was empty",
            "(agent produced empty output)",
            "agent produced empty output",
        ):
            return not suggestions
    return False


class CritiqueGenerator:
    """
    Generates critiques in parallel with bounded concurrency.

    This class handles the parallel generation of critiques from multiple
    critics for multiple proposals, with semaphore-bounded concurrency
    to prevent API rate limit exhaustion.

    Usage:
        generator = CritiqueGenerator(
            critique_with_agent=arena._critique_with_agent,
            with_timeout=arena._with_timeout,
            circuit_breaker=arena.circuit_breaker,
            hooks=arena.hooks,
            recorder=arena.recorder,
            select_critics_for_proposal=arena._select_critics_for_proposal,
            notify_spectator=arena._notify_spectator,
        )
        await generator.execute_critique_phase(ctx, critics, round_num, result)
    """

    def __init__(
        self,
        critique_with_agent: Callable | None = None,
        with_timeout: Callable | None = None,
        circuit_breaker: Any | None = None,
        hooks: dict | None = None,
        recorder: Any | None = None,
        select_critics_for_proposal: Callable | None = None,
        notify_spectator: Callable | None = None,
        heartbeat_callback: Callable | None = None,
        max_concurrent: int = MAX_CONCURRENT_CRITIQUES,
        # Molecule tracking for work unit management (Gastown pattern)
        molecule_tracker: MoleculeTracker | None = None,
    ):
        """
        Initialize the critique generator.

        Args:
            critique_with_agent: Async callback for generating critique
            with_timeout: Async timeout wrapper callback
            circuit_breaker: Circuit breaker for agent failure tracking
            hooks: Dictionary of event hooks
            recorder: Debate recorder for logging turns
            select_critics_for_proposal: Callback to select critics for a proposal
            notify_spectator: Callback for spectator notifications
            heartbeat_callback: Callback for emitting heartbeats
            max_concurrent: Maximum concurrent critique generations
        """
        self._critique_with_agent = critique_with_agent
        self._with_timeout = with_timeout
        self.circuit_breaker = circuit_breaker
        self.hooks = hooks or {}
        self.recorder = recorder
        self._select_critics_for_proposal = select_critics_for_proposal
        self._notify_spectator = notify_spectator
        self._emit_heartbeat = heartbeat_callback
        self._max_concurrent = max_concurrent

        # Molecule tracking for work unit management
        self._molecule_tracker = molecule_tracker
        self._active_molecules: dict[str, str] = {}  # "critic:target" -> molecule_id

    @staticmethod
    def _classify_error(error: Exception) -> str:
        if isinstance(error, asyncio.TimeoutError):
            return "timeout"
        message = str(error).lower()
        if "empty" in message:
            return "empty"
        return "exception"

    async def execute_critique_phase(
        self,
        ctx: DebateContext,
        critics: list[Agent],
        round_num: int,
        partial_messages: list[Message],
        partial_critiques: list[Critique],
    ) -> tuple[list[Message], list[Critique]]:
        """
        Execute critique phase with parallel generation.

        Args:
            ctx: The DebateContext with proposals
            critics: List of agents who can critique
            round_num: Current round number
            partial_messages: List to append new messages to
            partial_critiques: List to append new critiques to

        Returns:
            Tuple of (new_messages, new_critiques) generated
        """

        result = ctx.result
        proposals = ctx.proposals
        new_messages: list[Message] = []
        new_critiques: list[Critique] = []

        critique_with_agent = self._critique_with_agent
        if critique_with_agent is None:
            logger.warning("No critique_with_agent callback, skipping critiques")
            return (new_messages, new_critiques)

        # Create critique tasks based on topology with bounded concurrency
        critique_semaphore = asyncio.Semaphore(self._max_concurrent)

        async def generate_critique(critic: Agent, proposal_agent: str, proposal: str):
            """Generate critique and return CritiqueResult."""
            logger.debug("critique_generating critic=%s target=%s", critic.name, proposal_agent)
            base_timeout = getattr(critic, "timeout", AGENT_TIMEOUT_SECONDS)
            timeout = get_complexity_governor().get_scaled_timeout(float(base_timeout))
            task_id = f"{critic.name}:critique:{proposal_agent}"

            try:
                with streaming_task_context(task_id):
                    with_timeout = self._with_timeout
                    if with_timeout is not None:
                        crit_result = await with_timeout(
                            critique_with_agent(
                                critic,
                                proposal,
                                ctx.env.task if ctx.env else "",
                                ctx.context_messages,
                                target_agent=proposal_agent,
                            ),
                            critic.name,
                            timeout_seconds=timeout,
                        )
                    else:
                        crit_result = await critique_with_agent(
                            critic,
                            proposal,
                            ctx.env.task if ctx.env else "",
                            ctx.context_messages,
                            target_agent=proposal_agent,
                        )

                if crit_result and _is_effectively_empty_critique(crit_result):
                    logger.warning(
                        "critique_empty_response_retry critic=%s target=%s",
                        critic.name,
                        proposal_agent,
                    )
                    retry_task_id = f"{critic.name}:critique:{proposal_agent}:retry"
                    with streaming_task_context(retry_task_id):
                        retry_with_timeout = self._with_timeout
                        if retry_with_timeout is not None:
                            crit_result = await retry_with_timeout(
                                critique_with_agent(
                                    critic,
                                    proposal,
                                    ctx.env.task if ctx.env else "",
                                    ctx.context_messages,
                                    target_agent=proposal_agent,
                                ),
                                critic.name,
                                timeout_seconds=timeout,
                            )
                        else:
                            crit_result = await critique_with_agent(
                                critic,
                                proposal,
                                ctx.env.task if ctx.env else "",
                                ctx.context_messages,
                                target_agent=proposal_agent,
                            )

                if crit_result and _is_effectively_empty_critique(crit_result):
                    return CritiqueResult(
                        critic=critic,
                        target_agent=proposal_agent,
                        critique=None,
                        error=ValueError("Agent response was empty"),
                    )
                return CritiqueResult(
                    critic=critic,
                    target_agent=proposal_agent,
                    critique=crit_result,
                    error=None,
                )
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                return CritiqueResult(
                    critic=critic,
                    target_agent=proposal_agent,
                    critique=None,
                    error=e,
                )

        async def generate_critique_bounded(critic: Agent, proposal_agent: str, proposal: str):
            """Wrap critique generation with semaphore for bounded concurrency."""
            async with critique_semaphore:
                # Emit agent_thinking event before critique generation
                if self._notify_spectator:
                    try:
                        self._notify_spectator(
                            "agent_thinking",
                            agent=critic.name,
                            step=f"Analyzing proposal from {proposal_agent}",
                            phase="critique",
                            round_num=round_num,
                        )
                    except (RuntimeError, AttributeError, TypeError):  # noqa: BLE001
                        pass
                # Mark molecule as in_progress
                self._start_molecule(critic.name, proposal_agent)
                return await generate_critique(critic, proposal_agent, proposal)

        # Enrich proposals with sandbox verification results if available
        sandbox_results = getattr(ctx, "sandbox_verification_results", None) or {}

        def _enrich_with_sandbox(agent_name: str, proposal_text: str) -> str:
            """Append sandbox verification info to proposal for critique context."""
            sb = sandbox_results.get(agent_name)
            if not sb:
                return proposal_text
            status = "PASSED" if sb.get("passed") else "FAILED"
            extra = f"\n\n[Sandbox Verification: {status}]"
            if sb.get("stdout"):
                extra += f"\nOutput: {sb['stdout'][:200]}"
            if sb.get("stderr"):
                extra += f"\nErrors: {sb['stderr'][:200]}"
            return proposal_text + extra

        # Filter out empty/placeholder proposals
        valid_proposals = {
            agent: content
            for agent, content in proposals.items()
            if content and "(Agent produced empty output)" not in content
        }
        if len(valid_proposals) < len(proposals):
            skipped = [a for a in proposals if a not in valid_proposals]
            logger.warning("critique_skip_empty_proposals skipped=%s", skipped)

        # Create tasks and molecules
        critique_tasks = []
        debate_id = getattr(ctx, "debate_id", None) or (ctx.env.task[:50] if ctx.env else "unknown")

        for proposal_agent, proposal in valid_proposals.items():
            if self._select_critics_for_proposal:
                selected_critics = self._select_critics_for_proposal(proposal_agent, critics)
            else:
                selected_critics = [c for c in critics if c.name != proposal_agent]

            # Enrich proposal with sandbox results for critique context
            enriched_proposal = _enrich_with_sandbox(proposal_agent, proposal)

            for critic in selected_critics:
                # Create molecule for this critique task
                self._create_critique_molecule(debate_id, round_num, critic.name, proposal_agent)
                critique_tasks.append(
                    asyncio.create_task(
                        generate_critique_bounded(critic, proposal_agent, enriched_proposal)
                    )
                )

        # Emit heartbeat before critique phase
        if self._emit_heartbeat:
            self._emit_heartbeat(f"critique_round_{round_num}", "generating_critiques")

        # Process critiques as they complete
        critique_count = 0
        total_critiques = len(critique_tasks)

        for completed_task in asyncio.as_completed(critique_tasks):
            try:
                crit_result: CritiqueResult = await completed_task
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - phase isolation
                logger.error("task_exception phase=critique error=%s", e)
                continue

            critique_count += 1

            # Emit heartbeat every 3 critiques
            if (
                critique_count % 3 == 0 or critique_count == total_critiques
            ) and self._emit_heartbeat:
                self._emit_heartbeat(
                    f"critique_round_{round_num}",
                    f"completed_{critique_count}_of_{total_critiques}",
                )

            # Process the result (modifies new_messages and new_critiques in place)
            self._process_critique_result(
                crit_result,
                ctx,
                round_num,
                result,
                new_messages,
                new_critiques,
                partial_messages,
                partial_critiques,
            )

        return (new_messages, new_critiques)

    def _process_critique_result(
        self,
        crit_result: CritiqueResult,
        ctx: DebateContext,
        round_num: int,
        result: Any,
        new_messages: list[Message],
        new_critiques: list[Critique],
        partial_messages: list[Message],
        partial_critiques: list[Critique],
    ) -> Critique | None:
        """Process a single critique result."""
        from aragora.core import Critique, Message

        critic = crit_result.critic
        proposal_agent = crit_result.target_agent

        if crit_result.critique and _is_effectively_empty_critique(crit_result.critique):
            provider = getattr(critic, "provider", None) or getattr(critic, "model_type", "unknown")
            logger.warning(
                "critique_empty_response critic=%s provider=%s target=%s",
                critic.name,
                provider,
                proposal_agent,
            )
            crit_result.critique = None
            crit_result.error = ValueError("Agent response was empty")

        if crit_result.error:
            logger.error(
                "critique_error critic=%s target=%s error=%s",
                critic.name,
                proposal_agent,
                crit_result.error,
            )
            error_type = self._classify_error(crit_result.error)
            provider = getattr(critic, "provider", None) or getattr(critic, "model_type", "unknown")
            ctx.record_agent_failure(
                critic.name,
                phase="critique",
                error_type=error_type,
                message=str(crit_result.error),
                provider=provider,
            )
            if "on_agent_error" in self.hooks:
                self.hooks["on_agent_error"](
                    agent=critic.name,
                    error_type=error_type,
                    message=str(crit_result.error),
                    recoverable=True,
                    phase="critique",
                )
            if self.circuit_breaker:
                self.circuit_breaker.record_failure(critic.name)
            # Create placeholder critique so the UI shows a failure instead of a silent drop
            placeholder = Critique(
                agent=critic.name,
                target_agent=proposal_agent,
                target_content=ctx.proposals.get(proposal_agent, ""),
                issues=[f"[Critique failed: {crit_result.error}]"],
                suggestions=[],
                severity=0.0,
                reasoning="Critique generation failed due to an exception.",
            )
            result.critiques.append(placeholder)
            partial_critiques.append(placeholder)
            new_critiques.append(placeholder)

            if "on_critique" in self.hooks:
                self.hooks["on_critique"](
                    agent=critic.name,
                    target=proposal_agent,
                    issues=placeholder.issues,
                    severity=placeholder.severity,
                    round_num=round_num,
                    full_content=placeholder.to_prompt(),
                    error=str(crit_result.error),
                )
            # Mark molecule as failed
            self._fail_molecule(critic.name, proposal_agent, str(crit_result.error))
            return placeholder

        if crit_result.critique is None:
            # Handle timeout/error case
            logger.warning(
                "critique_returned_none critic=%s target=%s", critic.name, proposal_agent
            )
            ctx.record_agent_failure(
                critic.name,
                phase="critique",
                error_type="timeout",
                message="Critique unavailable - agent timed out or returned empty output",
                provider=getattr(critic, "provider", None)
                or getattr(critic, "model_type", "unknown"),
            )
            if "on_agent_error" in self.hooks:
                self.hooks["on_agent_error"](
                    agent=critic.name,
                    error_type="timeout",
                    message="Critique unavailable - agent timed out or returned empty output",
                    recoverable=True,
                    phase="critique",
                )
            if self.circuit_breaker:
                self.circuit_breaker.record_failure(critic.name)

            # Create placeholder critique
            placeholder = Critique(
                agent=critic.name,
                target_agent=proposal_agent,
                target_content=ctx.proposals.get(proposal_agent, ""),
                issues=["[Critique unavailable - agent timed out or encountered an error]"],
                suggestions=[],
                severity=0.0,
                reasoning="Critique generation failed due to timeout or agent error.",
            )
            result.critiques.append(placeholder)
            partial_critiques.append(placeholder)
            new_critiques.append(placeholder)

            # Emit placeholder event
            if "on_critique" in self.hooks:
                self.hooks["on_critique"](
                    agent=critic.name,
                    target=proposal_agent,
                    issues=placeholder.issues,
                    severity=placeholder.severity,
                    round_num=round_num,
                    full_content=placeholder.to_prompt(),
                )
            # Mark molecule as failed
            self._fail_molecule(
                critic.name, proposal_agent, "Critique unavailable - agent timed out"
            )
            return placeholder

        # Successful critique
        critique = crit_result.critique
        if self.circuit_breaker:
            self.circuit_breaker.record_success(critic.name)

        result.critiques.append(critique)
        partial_critiques.append(critique)
        new_critiques.append(critique)

        logger.debug(
            f"critique_complete critic={critic.name} target={proposal_agent} "
            f"issues={len(critique.issues)} severity={critique.severity:.1f}"
        )

        # Notify spectator
        if self._notify_spectator:
            self._notify_spectator(
                "critique",
                agent=critic.name,
                details=f"Critiqued {proposal_agent}: {len(critique.issues)} issues",
                metric=critique.severity,
            )

        # Get full critique content
        critique_content = critique.to_prompt()

        # Emit critique event
        if "on_critique" in self.hooks:
            self.hooks["on_critique"](
                agent=critic.name,
                target=proposal_agent,
                issues=critique.issues,
                severity=critique.severity,
                round_num=round_num,
                full_content=critique_content,
            )

        # Emit crux_identified for high-severity critiques (>= 0.7)
        # High severity critiques identify key disagreements worth surfacing
        if critique.severity >= 0.7 and critique.issues and self._notify_spectator:
            try:
                crux_description = critique.issues[0][:300] if critique.issues else ""
                self._notify_spectator(
                    "crux_identified",
                    crux_description=crux_description,
                    agents_disagreeing=[critic.name, proposal_agent],
                    positions={
                        critic.name: "challenges",
                        proposal_agent: "defends",
                    },
                    severity=critique.severity,
                    round_num=round_num,
                )
            except (RuntimeError, AttributeError, TypeError):  # noqa: BLE001
                pass

        # Record critique
        if self.recorder:
            try:
                self.recorder.record_turn(critic.name, critique_content, round_num)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Recorder error for critique: %s", e)

        # Add to context
        msg = Message(
            role="critic",
            agent=critic.name,
            content=critique_content,
            round=round_num,
        )
        ctx.add_message(msg)  # also appends to result.messages (#9661)
        partial_messages.append(msg)
        new_messages.append(msg)

        # Mark molecule as completed
        self._complete_molecule(
            critic.name,
            proposal_agent,
            {
                "issues": len(critique.issues),
                "severity": critique.severity,
            },
        )

        return critique

    # Molecule tracking methods (Gastown pattern)

    def _create_critique_molecule(
        self,
        debate_id: str,
        round_num: int,
        critic_name: str,
        target_name: str,
    ) -> None:
        """Create a critique molecule for tracking.

        Args:
            debate_id: ID of the current debate
            round_num: Current round number
            critic_name: Name of the critic agent
            target_name: Name of the target agent being critiqued
        """
        if not self._molecule_tracker:
            return

        try:
            from aragora.debate.molecules import MoleculeType

            molecule = self._molecule_tracker.create_molecule(
                debate_id=debate_id,
                molecule_type=MoleculeType.CRITIQUE,
                round_number=round_num,
                input_data={"critic": critic_name, "target": target_name},
            )
            key = f"{critic_name}:{target_name}"
            self._active_molecules[key] = molecule.molecule_id
            logger.debug(
                "[molecule] Created critique molecule %s critic=%s target=%s",
                molecule.molecule_id,
                critic_name,
                target_name,
            )
        except ImportError:
            logger.debug("[molecule] Molecule imports unavailable")
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.debug("[molecule] Failed to create critique molecule: %s", e)

    def _start_molecule(self, critic_name: str, target_name: str) -> None:
        """Mark a critique molecule as in_progress.

        Args:
            critic_name: Name of the critic agent
            target_name: Name of the target agent
        """
        if not self._molecule_tracker:
            return

        key = f"{critic_name}:{target_name}"
        molecule_id = self._active_molecules.get(key)
        if molecule_id:
            try:
                self._molecule_tracker.start_molecule(molecule_id)
                logger.debug("[molecule] Started critique molecule %s", molecule_id)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to start molecule: %s", e)

    def _complete_molecule(self, critic_name: str, target_name: str, output: dict) -> None:
        """Mark a critique molecule as completed.

        Args:
            critic_name: Name of the critic agent
            target_name: Name of the target agent
            output: Output data from the critique
        """
        if not self._molecule_tracker:
            return

        key = f"{critic_name}:{target_name}"
        molecule_id = self._active_molecules.get(key)
        if molecule_id:
            try:
                self._molecule_tracker.complete_molecule(molecule_id, output)
                logger.debug("[molecule] Completed critique molecule %s", molecule_id)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to complete molecule: %s", e)

    def _fail_molecule(self, critic_name: str, target_name: str, error: str) -> None:
        """Mark a critique molecule as failed.

        Args:
            critic_name: Name of the critic agent
            target_name: Name of the target agent
            error: Error message
        """
        if not self._molecule_tracker:
            return

        key = f"{critic_name}:{target_name}"
        molecule_id = self._active_molecules.get(key)
        if molecule_id:
            try:
                self._molecule_tracker.fail_molecule(molecule_id, error)
                logger.debug("[molecule] Failed critique molecule %s: %s", molecule_id, error)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to record molecule failure: %s", e)
