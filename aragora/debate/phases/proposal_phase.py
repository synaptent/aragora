"""
Proposal phase for debate orchestration.

This module extracts the initial proposal generation logic (Phase 1) from the
Arena._run_inner() method, handling:
- Proposer selection and circuit breaker filtering
- Parallel proposal generation with streaming
- Position tracking for grounded personas
- Message and event emission
- Citation need extraction
"""

from __future__ import annotations

__all__ = [
    "ProposalPhase",
]

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import (
    AGENT_TIMEOUT_SECONDS,
    MAX_CONCURRENT_PROPOSALS,
    PROPOSAL_STAGGER_SECONDS,
)
from aragora.debate.complexity_governor import get_complexity_governor
from aragora.debate.types import AgentType, DebateContextType
from aragora.events.context import streaming_task_context

if TYPE_CHECKING:
    from aragora.debate.molecules import MoleculeTracker

logger = logging.getLogger(__name__)


def _record_calibration_adjustment(agent: str) -> None:
    """Record calibration adjustment metric with lazy import."""
    try:
        from aragora.observability.metrics import record_calibration_adjustment

        record_calibration_adjustment(agent)
    except ImportError:
        logger.debug("Calibration adjustment metrics not available")


class ProposalPhase:
    """
    Generates initial proposals from proposer agents.

    This class encapsulates the parallel proposal generation logic that was
    previously in Arena._run_inner() for round 0.

    Usage:
        proposal_phase = ProposalPhase(
            circuit_breaker=arena.circuit_breaker,
            position_tracker=arena.position_tracker,
            recorder=arena.recorder,
            hooks=arena.hooks,
        )
        await proposal_phase.execute(ctx)
    """

    def __init__(
        self,
        circuit_breaker: Any = None,
        position_tracker: Any = None,
        position_ledger: Any = None,
        recorder: Any = None,
        hooks: dict | None = None,
        # Calibration for proposal confidence scaling
        calibration_tracker: Any = None,
        # Callbacks for orchestrator methods
        build_proposal_prompt: Callable | None = None,
        generate_with_agent: Callable | None = None,
        with_timeout: Callable | None = None,
        notify_spectator: Callable | None = None,
        update_role_assignments: Callable | None = None,
        record_grounded_position: Callable | None = None,
        extract_citation_needs: Callable | None = None,
        # Propulsion engine for push-based work assignment (Gastown pattern)
        propulsion_engine: Any = None,
        enable_propulsion: bool = False,
        # Molecule tracking for work unit management (Gastown pattern)
        molecule_tracker: MoleculeTracker | None = None,
        # Arena config for feature flags (sandbox verification, etc.)
        arena_config: Any = None,
        # Optional phase-local timeout override. None preserves adaptive defaults.
        proposal_timeout_seconds: float | None = None,
    ):
        """
        Initialize the proposal phase.

        Args:
            circuit_breaker: CircuitBreaker for agent availability
            position_tracker: Optional PositionTracker for personas
            position_ledger: Optional PositionLedger for grounded personas
            recorder: Optional ReplayRecorder
            hooks: Optional hooks dict for events
            calibration_tracker: Optional CalibrationTracker for confidence scaling
            build_proposal_prompt: Callback to build proposal prompt
            generate_with_agent: Async callback to generate with agent
            with_timeout: Async callback for timeout wrapper
            notify_spectator: Callback for spectator notifications
            update_role_assignments: Callback to update role assignments
            record_grounded_position: Callback to record grounded position
            extract_citation_needs: Callback to extract citation needs
        """
        self.circuit_breaker = circuit_breaker
        self.position_tracker = position_tracker
        self.position_ledger = position_ledger
        self.recorder = recorder
        self.hooks = hooks or {}
        self.calibration_tracker = calibration_tracker

        # Callbacks
        self._build_proposal_prompt = build_proposal_prompt
        self._generate_with_agent = generate_with_agent
        self._with_timeout = with_timeout
        self._notify_spectator = notify_spectator
        self._update_role_assignments = update_role_assignments
        self._record_grounded_position = record_grounded_position
        self._extract_citation_needs = extract_citation_needs

        # Propulsion engine for push-based work assignment
        self._propulsion_engine = propulsion_engine
        self._enable_propulsion = enable_propulsion

        # Molecule tracking for work unit management
        self._molecule_tracker = molecule_tracker
        self._active_molecules: dict[str, str] = {}  # agent_name -> molecule_id

        # Arena config for feature flags
        self._arena_config = arena_config
        self.proposal_timeout_seconds = proposal_timeout_seconds

    @staticmethod
    def _is_effectively_empty_response(content: Any) -> bool:
        if not isinstance(content, str):
            return False
        normalized = content.strip().lower()
        return not normalized or normalized in (
            "agent response was empty",
            "(agent produced empty output)",
            "agent produced empty output",
        )

    @staticmethod
    def _classify_error(error: Exception) -> str:
        if isinstance(error, asyncio.TimeoutError):
            return "timeout"
        message = str(error).lower()
        if "empty" in message:
            return "empty"
        return "exception"

    async def execute(self, ctx: DebateContextType) -> None:
        """
        Execute the proposal phase.

        Args:
            ctx: The DebateContextType to update with proposals
        """
        # Check for cancellation before starting
        if hasattr(ctx, "cancellation_token") and ctx.cancellation_token:
            if ctx.cancellation_token.is_cancelled:
                from aragora.debate.cancellation import DebateCancelled

                raise DebateCancelled(ctx.cancellation_token.reason)

        # Trigger PRE_DEBATE hook if hook_manager is available
        if hasattr(ctx, "hook_manager") and ctx.hook_manager:
            try:
                await ctx.hook_manager.trigger(
                    "pre_debate", ctx=ctx, agents=ctx.agents, task=ctx.env.task
                )
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("PRE_DEBATE hook failed: %s", e)

        # 1. Update role assignments for round 0
        if self._update_role_assignments:
            self._update_role_assignments(round_num=0)

        # 2. Log debate start
        agent_names = [a.name for a in ctx.agents]
        logger.info("debate_start task=%s agents=%s", ctx.env.task[:80], agent_names)

        # 3. Emit debate start event
        self._emit_debate_start(ctx)

        # 4. Notify spectator
        if self._notify_spectator:
            self._notify_spectator(
                "debate_start",
                details=f"Task: {ctx.env.task[:50]}...",
                agent="system",
            )

        # 5. Filter proposers through circuit breaker
        logger.info("round_start round=0 phase=proposals")
        available_proposers = self._filter_proposers(ctx)

        # 6. Generate proposals in parallel
        await self._generate_proposals_parallel(ctx, available_proposers)

        # 7. Extract citation needs
        if self._extract_citation_needs:
            self._extract_citation_needs(ctx.proposals)

        # 7.5. Sandbox verification of code proposals
        await self._run_sandbox_verification(ctx)

        # 8. Fire propulsion event (proposals_ready) for push-based flow
        await self._fire_propulsion_event(ctx)

    def _emit_debate_start(self, ctx: DebateContextType) -> None:
        """Emit debate start hook event."""
        if "on_debate_start" not in self.hooks:
            return

        self.hooks["on_debate_start"](
            ctx.env.task,
            [a.name for a in ctx.agents],
        )

    def _filter_proposers(self, ctx: DebateContextType) -> list[AgentType]:
        """Filter proposers through circuit breaker."""
        proposers = ctx.proposers

        if not self.circuit_breaker:
            return proposers

        try:
            available = self.circuit_breaker.filter_available_agents(proposers)
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.error("Circuit breaker filter error: %s", e)
            return proposers  # Fall back to all proposers

        if len(available) < len(proposers):
            skipped = [a.name for a in proposers if a not in available]
            logger.info("circuit_breaker_skip agents=%s", skipped)

        return available

    async def _generate_proposals_parallel(
        self, ctx: DebateContextType, proposers: list[AgentType]
    ) -> None:
        """Generate proposals in parallel with bounded concurrency."""

        if not proposers:
            logger.warning("No proposers available for proposal phase")
            return

        # Create molecules for tracking if tracker is available
        debate_id = getattr(ctx, "debate_id", None) or (ctx.env.task[:50] if ctx.env else "unknown")
        self._create_proposal_molecules(debate_id, proposers, ctx.env.task if ctx.env else "")

        # Use semaphore for bounded concurrency (matching critique/revision phases)
        # Legacy stagger mode available via PROPOSAL_STAGGER_SECONDS > 0
        proposal_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROPOSALS)

        async def generate_proposal_bounded(idx: int, agent: AgentType) -> tuple[AgentType, Any]:
            """Generate proposal with semaphore-bounded concurrency."""
            # Optional stagger delay for backward compatibility
            if PROPOSAL_STAGGER_SECONDS > 0 and idx > 0:
                await asyncio.sleep(PROPOSAL_STAGGER_SECONDS * idx)
            async with proposal_semaphore:
                logger.info("proposal_started agent=%s idx=%s", agent.name, idx)
                # Mark molecule as in_progress
                self._start_molecule(agent.name)
                return await self._generate_single_proposal(ctx, agent)

        # Create all tasks immediately (semaphore controls actual concurrency)
        tasks = [
            asyncio.create_task(
                generate_proposal_bounded(idx, agent), name=f"proposal_{agent.name}"
            )
            for idx, agent in enumerate(proposers)
        ]

        try:
            # Wait for all proposals and process as they complete.
            # Track time-to-first-response for latency visibility (issue #268).
            _first_response_logged = False
            _proposals_start = time.perf_counter()
            for completed_task in asyncio.as_completed(tasks):
                try:
                    agent, result_or_error = await completed_task
                except asyncio.CancelledError:
                    raise  # Propagate cancellation
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.error("task_exception phase=proposal error=%s", e)
                    continue

                if not _first_response_logged:
                    _first_ms = (time.perf_counter() - _proposals_start) * 1000
                    logger.info("time_to_first_proposal_ms=%.1f agent=%s", _first_ms, agent.name)
                    _first_response_logged = True

                # Process the result
                self._process_proposal_result(ctx, agent, result_or_error)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _generate_single_proposal(
        self, ctx: DebateContextType, agent: AgentType
    ) -> tuple[AgentType, Any]:
        """Generate a single proposal from an agent."""
        if not self._build_proposal_prompt or not self._generate_with_agent:
            return (agent, Exception("Missing callbacks"))

        prompt = self._build_proposal_prompt(agent)
        logger.debug("agent_generating agent=%s phase=proposal", agent.name)

        # Emit agent_thinking event before generation starts
        if self._notify_spectator:
            try:
                self._notify_spectator(
                    "agent_thinking",
                    agent=agent.name,
                    step="Formulating initial proposal",
                    phase="proposal",
                    round_num=0,
                )
            except (RuntimeError, AttributeError, TypeError):  # noqa: BLE001
                pass

        # Track timing for governor feedback
        start_time = time.perf_counter()
        governor = get_complexity_governor()

        try:
            # Use complexity-scaled timeout from governor
            if self.proposal_timeout_seconds is None:
                base_timeout = getattr(agent, "timeout", AGENT_TIMEOUT_SECONDS)
                timeout = governor.get_scaled_timeout(float(base_timeout))
            else:
                timeout = float(self.proposal_timeout_seconds)
                if timeout <= 0:
                    raise ValueError("proposal_timeout_seconds must be positive")
            # Use unique task_id to prevent token interleaving between concurrent agents
            task_id = f"{agent.name}:proposal"
            with streaming_task_context(task_id):
                if self._with_timeout:
                    result = await self._with_timeout(
                        self._generate_with_agent(agent, prompt, ctx.context_messages),
                        agent.name,
                        timeout_seconds=timeout,
                    )
                else:
                    result = await self._generate_with_agent(agent, prompt, ctx.context_messages)
            if self._is_effectively_empty_response(result):
                logger.warning("agent_empty_response_retry agent=%s phase=proposal", agent.name)
                retry_task_id = f"{agent.name}:proposal:retry"
                with streaming_task_context(retry_task_id):
                    if self._with_timeout:
                        result = await self._with_timeout(
                            self._generate_with_agent(agent, prompt, ctx.context_messages),
                            agent.name,
                            timeout_seconds=timeout,
                        )
                    else:
                        result = await self._generate_with_agent(
                            agent, prompt, ctx.context_messages
                        )
            if self._is_effectively_empty_response(result):
                # Record failure to governor
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(agent.name, latency_ms, success=False)
                return (agent, ValueError("Agent response was empty"))

            # Record success to governor
            latency_ms = (time.perf_counter() - start_time) * 1000
            governor.record_agent_response(agent.name, latency_ms, success=True)
            return (agent, result)
        except asyncio.TimeoutError as e:
            # Record timeout to governor
            governor.record_agent_timeout(agent.name, timeout)
            return (agent, e)
        except Exception as e:  # noqa: BLE001 - phase isolation
            # Record failure to governor
            latency_ms = (time.perf_counter() - start_time) * 1000
            governor.record_agent_response(agent.name, latency_ms, success=False)
            return (agent, e)

    def _process_proposal_result(
        self, ctx: DebateContextType, agent: AgentType, result_or_error: Any
    ) -> None:
        """Process a proposal result from an agent."""
        from aragora.core import Message

        is_error = isinstance(result_or_error, Exception)

        if not is_error and self._is_effectively_empty_response(result_or_error):
            provider = getattr(agent, "provider", None) or getattr(agent, "model_type", "unknown")
            logger.warning(
                "agent_empty_response agent=%s provider=%s phase=proposal", agent.name, provider
            )
            result_or_error = ValueError("Agent response was empty")
            is_error = True

        if is_error:
            logger.error(
                "agent_error agent=%s phase=proposal error=%s", agent.name, result_or_error
            )
            error_type = self._classify_error(result_or_error)
            provider = getattr(agent, "provider", None) or getattr(agent, "model_type", "unknown")
            ctx.record_agent_failure(
                agent.name,
                phase="proposal",
                error_type=error_type,
                message=str(result_or_error),
                provider=provider,
            )
            if "on_agent_error" in self.hooks:
                self.hooks["on_agent_error"](
                    agent=agent.name,
                    error_type=error_type,
                    message=str(result_or_error),
                    recoverable=True,
                    phase="proposal",
                )
            ctx.proposals[agent.name] = f"[Error generating proposal: {result_or_error}]"
            if self.circuit_breaker:
                self.circuit_breaker.record_failure(agent.name)
            # Mark molecule as failed
            self._fail_molecule(agent.name, str(result_or_error))
        else:
            ctx.proposals[agent.name] = result_or_error
            logger.info(
                "agent_complete agent=%s phase=proposal chars=%s", agent.name, len(result_or_error)
            )
            if self.circuit_breaker:
                self.circuit_breaker.record_success(agent.name)

            # Notify spectator
            if self._notify_spectator:
                self._notify_spectator(
                    "propose",
                    agent=agent.name,
                    details=f"Initial proposal ({len(result_or_error)} chars)",
                    metric=len(result_or_error),
                )

            # Emit argument strength based on response length heuristic
            if self._notify_spectator:
                try:
                    content = result_or_error
                    content_len = len(content)

                    # Detail: length-based (existing heuristic)
                    detail = min(1.0, max(0.3, content_len / 3000))

                    # Completeness: structural markers (headings, bullets, code)
                    markers = sum(
                        [
                            content.count("\n#") * 2,  # Headings
                            content.count("\n- ") * 1,  # Bullet points
                            content.count("\n1.") * 1,  # Numbered lists
                            content.count("```") * 3,  # Code blocks
                            content.count("**") * 0.5,  # Bold emphasis
                        ]
                    )
                    completeness = min(1.0, max(0.2, markers / 20))

                    # Specificity: numbers, percentages, technical terms
                    import re

                    specifics = len(re.findall(r"\d+%|\$\d+|\d+\.\d+|e\.g\.|i\.e\.", content))
                    specificity = min(1.0, max(0.2, specifics / 8))

                    # Composite score from independent signals
                    strength = round(detail * 0.4 + completeness * 0.35 + specificity * 0.25, 3)

                    self._notify_spectator(
                        "argument_strength",
                        agent=agent.name,
                        argument_summary=content[:200],
                        strength_score=strength,
                        factors={
                            "detail": round(detail, 3),
                            "completeness": round(completeness, 3),
                            "specificity": round(specificity, 3),
                        },
                        round_num=0,
                    )
                except (RuntimeError, AttributeError, TypeError):  # noqa: BLE001
                    pass

            # Record positions
            self._record_positions(ctx, agent, result_or_error)

            # Mark molecule as completed
            self._complete_molecule(
                agent.name,
                {
                    "proposal": result_or_error[:500],  # Truncate for storage
                    "chars": len(result_or_error),
                },
            )

        # Create and add message
        msg = Message(
            role="proposer",
            agent=agent.name,
            content=ctx.proposals[agent.name],
            round=0,
        )
        ctx.add_message(msg)

        # Emit message event
        self._emit_message_event(agent, ctx.proposals[agent.name])

        # Record to replay recorder
        if self.recorder and not is_error:
            try:
                self.recorder.record_turn(agent.name, ctx.proposals[agent.name], 0)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Recorder error for proposal: %s", e)

    def _record_positions(self, ctx: DebateContextType, agent: AgentType, proposal: str) -> None:
        """Record positions for truth-grounded personas."""
        debate_id = ctx.debate_id or ctx.env.task[:50]

        # Base proposal confidence (default heuristic)
        raw_confidence = 0.7

        # Apply calibration scaling if available
        calibrated_confidence = self._get_calibrated_confidence(agent.name, raw_confidence, ctx)

        # Legacy position tracker
        if self.position_tracker:
            try:
                self.position_tracker.record_position(
                    debate_id=debate_id,
                    agent_name=agent.name,
                    position_type="proposal",
                    position_text=proposal[:1000],
                    round_num=0,
                    confidence=calibrated_confidence,
                )
            except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
                logger.debug("Position tracking error: %s", e)

        # New grounded position system
        if self._record_grounded_position:
            self._record_grounded_position(
                agent.name, proposal, debate_id, 0, calibrated_confidence
            )

    def _get_calibrated_confidence(
        self, agent_name: str, raw_confidence: float, ctx: DebateContextType
    ) -> float:
        """Apply calibration scaling to confidence value.

        Uses temperature scaling from CalibrationTracker if available and agent
        has sufficient prediction history.

        Args:
            agent_name: Name of the agent
            raw_confidence: Raw confidence value (0-1)
            ctx: Debate context for domain information

        Returns:
            Calibrated confidence, or raw confidence if calibration unavailable
        """
        if not self.calibration_tracker:
            return raw_confidence

        try:
            domain = getattr(ctx, "domain", None) or "general"
            summary = self.calibration_tracker.get_calibration_summary(agent_name)

            if summary and summary.total_predictions >= 10:
                calibrated = summary.adjust_confidence(raw_confidence, domain=domain)
                if calibrated != raw_confidence:
                    logger.debug(
                        f"[calibration] {agent_name} proposal confidence: "
                        f"{raw_confidence:.2f} -> {calibrated:.2f}"
                    )
                    _record_calibration_adjustment(agent_name)
                return calibrated
        except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
            logger.debug("[calibration] Failed for %s: %s", agent_name, e)

        return raw_confidence

    def _emit_message_event(self, agent: AgentType, content: str) -> None:
        """Emit on_message hook event and agent_message for TTS integration."""
        # Legacy hook for backwards compatibility
        if "on_message" in self.hooks:
            self.hooks["on_message"](
                agent=agent.name,
                content=content,
                role="proposer",
                round_num=0,
            )

        # Emit via spectator notification for EventBus/TTS integration
        if self._notify_spectator:
            try:
                self._notify_spectator(
                    "agent_message",
                    agent=agent.name,
                    content=content,
                    role="proposer",
                    round_num=0,
                    enable_tts=True,
                )
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Spectator notification failed: %s", e)

    async def _run_sandbox_verification(self, ctx: DebateContextType) -> None:
        """Run sandbox verification on proposals containing code blocks.

        When enable_sandbox_verification is set in the arena config, extracts
        code blocks from each proposal and runs them in the sandbox executor.
        Results are stored on ctx as sandbox_verification_results dict.

        Args:
            ctx: The DebateContext with proposals to verify.
        """
        if not getattr(self._arena_config, "enable_sandbox_verification", False):
            return

        if not ctx.proposals:
            return

        try:
            from aragora.debate.phases.sandbox_verifier import verify_code_proposal
        except (ImportError, RuntimeError) as e:
            logger.debug("Sandbox verification unavailable: %s", e)
            return

        results: dict[str, dict] = {}
        for agent_name, proposal_text in ctx.proposals.items():
            if not proposal_text or proposal_text.startswith("[Error"):
                continue
            try:
                sb_result = await verify_code_proposal(proposal_text)
                results[agent_name] = sb_result.to_dict()
                if not sb_result.passed:
                    logger.info(
                        "sandbox_verification_failed agent=%s error=%s",
                        agent_name,
                        sb_result.error_message or sb_result.stderr[:100],
                    )
            except (ImportError, RuntimeError, ValueError) as e:
                logger.debug("Sandbox verification skipped for %s: %s", agent_name, e)

        if results:
            # Store on ctx for downstream phases (critique) to access
            ctx.sandbox_verification_results = results  # type: ignore[attr-defined]
            logger.info(
                "sandbox_verification_complete agents=%s passed=%s",
                list(results.keys()),
                sum(1 for r in results.values() if r.get("passed")),
            )

    async def _fire_propulsion_event(self, ctx: DebateContextType) -> None:
        """Fire propulsion event to push work to the next stage.

        Triggers "proposals_ready" event with all generated proposals,
        enabling reactive debate flow via the Gastown pattern.

        Args:
            ctx: The DebateContext with proposals
        """
        if not self._enable_propulsion or not self._propulsion_engine:
            return

        try:
            from aragora.debate.propulsion import PropulsionPayload, PropulsionPriority

            # Create payload with proposal data
            payload = PropulsionPayload(
                data={
                    "proposals": dict(ctx.proposals),
                    "agent_count": len(ctx.proposals),
                    "debate_id": getattr(ctx, "debate_id", None),
                    "task": ctx.env.task[:200] if ctx.env else None,
                },
                priority=PropulsionPriority.NORMAL,
                source_stage="proposal_phase",
                source_molecule_id=getattr(ctx, "debate_id", None),
            )

            # Fire the propulsion event
            results = await self._propulsion_engine.propel("proposals_ready", payload)

            if results:
                success_count = sum(1 for r in results if r.success)
                logger.info(
                    "[propulsion] proposals_ready fired handlers=%s success=%s",
                    len(results),
                    success_count,
                )
        except ImportError:
            logger.debug("[propulsion] PropulsionEngine imports unavailable")
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.warning("[propulsion] Failed to fire proposals_ready: %s", e)

    # Molecule tracking methods (Gastown pattern)

    def _create_proposal_molecules(
        self,
        debate_id: str,
        proposers: list[AgentType],
        task: str,
    ) -> None:
        """Create proposal molecules for all proposers.

        Args:
            debate_id: ID of the current debate
            proposers: List of proposer agents
            task: The debate task description
        """
        if not self._molecule_tracker:
            return

        try:
            from aragora.debate.molecules import MoleculeType

            for agent in proposers:
                molecule = self._molecule_tracker.create_molecule(
                    debate_id=debate_id,
                    molecule_type=MoleculeType.PROPOSAL,
                    round_number=0,
                    input_data={"task": task, "agent": agent.name},
                )
                self._active_molecules[agent.name] = molecule.molecule_id
                logger.debug(
                    "[molecule] Created proposal molecule %s for agent=%s",
                    molecule.molecule_id,
                    agent.name,
                )
        except ImportError:
            logger.debug("[molecule] Molecule imports unavailable")
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.debug("[molecule] Failed to create proposal molecules: %s", e)

    def _start_molecule(self, agent_name: str) -> None:
        """Mark a molecule as in_progress.

        Args:
            agent_name: Name of the agent whose molecule to start
        """
        if not self._molecule_tracker:
            return

        molecule_id = self._active_molecules.get(agent_name)
        if molecule_id:
            try:
                self._molecule_tracker.start_molecule(molecule_id)
                logger.debug("[molecule] Started molecule %s for %s", molecule_id, agent_name)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to start molecule: %s", e)

    def _complete_molecule(self, agent_name: str, output: dict) -> None:
        """Mark a molecule as completed.

        Args:
            agent_name: Name of the agent whose molecule to complete
            output: Output data from the proposal generation
        """
        if not self._molecule_tracker:
            return

        molecule_id = self._active_molecules.get(agent_name)
        if molecule_id:
            try:
                self._molecule_tracker.complete_molecule(molecule_id, output)
                logger.debug("[molecule] Completed molecule %s for %s", molecule_id, agent_name)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to complete molecule: %s", e)

    def _fail_molecule(self, agent_name: str, error: str) -> None:
        """Mark a molecule as failed.

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
                logger.debug(
                    "[molecule] Failed molecule %s for %s: %s", molecule_id, agent_name, error
                )
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[molecule] Failed to record molecule failure: %s", e)
