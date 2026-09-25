"""
Consensus phase for debate orchestration.

This module extracts the consensus/voting logic (Phase 3) from the
Arena._run_inner() method, handling:
- None mode: No consensus, combine all proposals
- Majority mode: Weighted voting with reputation/reliability/consistency/calibration
- Unanimous mode: All agents must agree
- Judge mode: Single judge synthesizes

Weight calculation and vote aggregation logic is extracted to:
- weight_calculator.py: WeightCalculator class
- vote_aggregator.py: VoteAggregator class, calculate_consensus_strength()
- vote_collector.py: VoteCollector class for parallel vote collection
- winner_selector.py: WinnerSelector class for consensus determination
- consensus_verification.py: ConsensusVerifier class for claim verification
- synthesis_generator.py: SynthesisGenerator class for final synthesis
"""

__all__ = [
    "ConsensusDependencies",
    "ConsensusCallbacks",
    "ConsensusPhase",
]

import asyncio
import copy
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.agents.errors import _build_error_action
from aragora.config import AGENT_TIMEOUT_SECONDS
from aragora.debate.crux_mode import CruxFinderDisabledError
from aragora.observability.metrics.debate_slo import record_consensus_detection_latency
from aragora.debate.phases._phase_invariant import require_phase_result
from aragora.debate.phases.consensus_verification import ConsensusVerifier
from aragora.debate.phases.synthesis_generator import SynthesisGenerator
from aragora.debate.phases.vote_bonus_calculator import VoteBonusCalculator
from aragora.debate.phases.vote_collector import (
    MajorityVoteCollection,
    SlotVote,
    VoteCollector,
    VoteCollectorConfig,
    VoterSlot,
    get_complexity_governor,
)
from aragora.debate.phases.weight_calculator import WeightCalculator
from aragora.debate.phases.winner_selector import WinnerSelector
from aragora.events.context import streaming_task_context

if TYPE_CHECKING:
    from aragora.core import Vote
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)


@dataclass
class ConsensusDependencies:
    """Core dependencies for consensus phase execution.

    Groups the system components needed for consensus resolution,
    making dependency injection cleaner and more explicit.
    """

    protocol: Any = None
    elo_system: Any = None
    memory: Any = None
    agent_weights: dict[str, float] = field(default_factory=dict)
    flip_detector: Any = None
    position_tracker: Any = None
    calibration_tracker: Any = None
    recorder: Any = None
    hooks: dict = field(default_factory=dict)
    user_votes: list = field(default_factory=list)


@dataclass
class ConsensusCallbacks:
    """Callback functions for consensus phase operations.

    Separates the callback dependencies from core dependencies,
    making the interface cleaner and more testable.
    """

    vote_with_agent: Callable | None = None
    with_timeout: Callable | None = None
    select_judge: Callable | None = None
    build_judge_prompt: Callable | None = None
    generate_with_agent: Callable | None = None
    group_similar_votes: Callable | None = None
    get_calibration_weight: Callable | None = None
    notify_spectator: Callable | None = None
    drain_user_events: Callable | None = None
    extract_debate_domain: Callable | None = None
    get_belief_analyzer: Callable | None = None
    user_vote_multiplier: Callable | None = None
    verify_claims: Callable | None = None  # Optional verification callback


@dataclass(frozen=True, slots=True)
class _UserVoteContribution:
    """One user-vote contribution resolved before agent voting begins."""

    choice: str
    intensity: Any
    user_id: str
    weight: float


@dataclass(frozen=True, slots=True)
class _VoteWeightPolicy:
    """Frozen vote-dependent bias controls for one majority decision."""

    enable_self_vote_mitigation: bool
    self_vote_mode: str
    self_vote_downweight: float
    enable_verbosity_normalization: bool
    verbosity_target_length: int
    verbosity_penalty_threshold: float
    verbosity_max_penalty: float

    @classmethod
    def from_protocol(cls, protocol: Any) -> "_VoteWeightPolicy":
        return cls(
            enable_self_vote_mitigation=bool(
                getattr(protocol, "enable_self_vote_mitigation", False)
            ),
            self_vote_mode=str(getattr(protocol, "self_vote_mode", "downweight")),
            self_vote_downweight=float(getattr(protocol, "self_vote_downweight", 0.5)),
            enable_verbosity_normalization=bool(
                getattr(protocol, "enable_verbosity_normalization", False)
            ),
            verbosity_target_length=int(getattr(protocol, "verbosity_target_length", 1000)),
            verbosity_penalty_threshold=float(
                getattr(protocol, "verbosity_penalty_threshold", 3.0)
            ),
            verbosity_max_penalty=float(getattr(protocol, "verbosity_max_penalty", 0.3)),
        )

    @property
    def vote_dependent(self) -> bool:
        return self.enable_self_vote_mitigation or self.enable_verbosity_normalization

    def resolve_slot_weights(
        self,
        slots: tuple[VoterSlot, ...],
        base_slot_weights: tuple[float, ...],
        ballots: tuple[SlotVote, ...],
        proposals: dict[str, str],
    ) -> tuple[float, ...]:
        """Apply existing bias factors without consulting mutable weight sources."""
        if not self.vote_dependent:
            return base_slot_weights

        from aragora.debate.phases.weight_calculator import WeightCalculatorConfig

        config = WeightCalculatorConfig(
            enable_reputation=False,
            enable_reliability=True,
            enable_consistency=False,
            enable_calibration=False,
            enable_elo_skill=False,
            enable_self_vote_mitigation=self.enable_self_vote_mitigation,
            self_vote_mode=self.self_vote_mode,
            self_vote_downweight=self.self_vote_downweight,
            enable_verbosity_normalization=self.enable_verbosity_normalization,
            verbosity_target_length=self.verbosity_target_length,
            verbosity_penalty_threshold=self.verbosity_penalty_threshold,
            verbosity_max_penalty=self.verbosity_max_penalty,
        )
        ballots_by_slot = {ballot.slot.index: ballot for ballot in ballots}
        resolved: list[float] = []
        for slot, base_weight in zip(slots, base_slot_weights, strict=True):
            ballot = ballots_by_slot.get(slot.index)
            if ballot is None:
                resolved.append(base_weight)
                continue
            calculator = WeightCalculator(
                agent_weights={slot.name: base_weight},
                config=config,
                enable_cache=False,
            )
            weight = calculator.compute_weights_with_context(
                [slot],
                [ballot.vote],
                proposals,
            )[slot.name]
            resolved.append(weight)
        return tuple(resolved)


@dataclass(frozen=True, slots=True)
class _MajoritySnapshot:
    """Immutable decision inputs for one majority-consensus attempt."""

    effective_threshold: float
    min_participation_ratio: float
    min_participation_count: int
    required_participation: int
    slots: tuple[VoterSlot, ...]
    proposal_items: tuple[tuple[str, str], ...]
    protocol: Any = field(repr=False, compare=False)
    task: str
    domain: str
    base_slot_weights: tuple[float, ...]
    fixed_slot_weights: tuple[float, ...] | None
    vote_weight_policy: _VoteWeightPolicy
    user_vote_contributions: tuple[_UserVoteContribution, ...]
    calibration_summaries: tuple[tuple[str, Any], ...] = field(repr=False, compare=False)
    evidence_pack: Any = field(repr=False, compare=False)
    initial_process_verification: Any = field(repr=False, compare=False)
    had_initial_process_verification: bool
    initial_verification_results: Any = field(repr=False, compare=False)
    initial_verification_bonuses: Any = field(repr=False, compare=False)
    group_similar_votes: Callable | None = field(repr=False, compare=False)
    verify_claims: Callable | None = field(repr=False, compare=False)
    position_shuffling_enabled: bool
    position_shuffling_permutations: int
    position_shuffling_seed: int | None
    agent_timeout: float
    collection_timeout: float
    rlm_early_termination_enabled: bool
    rlm_early_termination_threshold: float
    rlm_majority_lead_threshold: float

    @classmethod
    def capture(
        cls,
        *,
        effective_threshold: float,
        agents: tuple[Any, ...],
        min_participation_ratio: float,
        min_participation_count: int,
        proposals: dict[str, str],
        protocol: Any,
        task: str,
        domain: str,
        base_weights_by_name: dict[str, float],
        tally_inputs_fixed: bool,
        user_vote_contributions: tuple[_UserVoteContribution, ...],
        calibration_summaries: tuple[tuple[str, Any], ...],
        evidence_pack: Any,
        result: Any,
        group_similar_votes: Callable | None,
        verify_claims: Callable | None,
        position_shuffling_enabled: bool,
        position_shuffling_permutations: int,
        position_shuffling_seed: int | None,
        agent_timeout: float,
        collection_timeout: float,
        rlm_early_termination_enabled: bool,
        rlm_early_termination_threshold: float,
        rlm_majority_lead_threshold: float,
    ) -> "_MajoritySnapshot":
        slots = tuple(
            VoterSlot(index=index, name=str(getattr(agent, "name", "")))
            for index, agent in enumerate(agents)
        )
        required = max(
            min_participation_count,
            math.ceil(len(slots) * min_participation_ratio),
        )
        required = min(required, max(len(slots), 1))
        result_metadata = getattr(result, "metadata", {})
        had_process_verification = (
            isinstance(result_metadata, dict) and "process_verification" in result_metadata
        )
        snapshot = cls(
            effective_threshold=effective_threshold,
            min_participation_ratio=min_participation_ratio,
            min_participation_count=min_participation_count,
            required_participation=required,
            slots=slots,
            proposal_items=tuple(copy.deepcopy(proposals).items()),
            protocol=copy.deepcopy(protocol),
            task=str(task),
            domain=str(domain),
            base_slot_weights=(),
            fixed_slot_weights=None,
            vote_weight_policy=_VoteWeightPolicy.from_protocol(protocol),
            user_vote_contributions=user_vote_contributions,
            calibration_summaries=calibration_summaries,
            evidence_pack=copy.deepcopy(evidence_pack),
            initial_process_verification=copy.deepcopy(
                result_metadata.get("process_verification")
                if isinstance(result_metadata, dict)
                else None
            ),
            had_initial_process_verification=had_process_verification,
            initial_verification_results=copy.deepcopy(getattr(result, "verification_results", {})),
            initial_verification_bonuses=copy.deepcopy(getattr(result, "verification_bonuses", {})),
            group_similar_votes=group_similar_votes,
            verify_claims=verify_claims,
            position_shuffling_enabled=position_shuffling_enabled,
            position_shuffling_permutations=position_shuffling_permutations,
            position_shuffling_seed=position_shuffling_seed,
            agent_timeout=agent_timeout,
            collection_timeout=collection_timeout,
            rlm_early_termination_enabled=rlm_early_termination_enabled,
            rlm_early_termination_threshold=rlm_early_termination_threshold,
            rlm_majority_lead_threshold=rlm_majority_lead_threshold,
        )
        base_slot_weights = snapshot.align_weights(base_weights_by_name)
        return replace(
            snapshot,
            base_slot_weights=base_slot_weights,
            fixed_slot_weights=base_slot_weights if tally_inputs_fixed else None,
        )

    @property
    def eligible_count(self) -> int:
        return len(self.slots)

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(slot.name for slot in self.slots)

    def proposals(self) -> dict[str, str]:
        """Return a new mutable view of the frozen proposal mapping."""
        return dict(self.proposal_items)

    def calibration_summary_map(self) -> dict[str, Any]:
        """Return detached calibration inputs captured at the decision boundary."""
        return copy.deepcopy(dict(self.calibration_summaries))

    def make_context_view(self, ctx: "DebateContext") -> "DebateContext":
        """Build an isolated context view for post-await decision helpers."""
        view = copy.copy(ctx)
        view.proposals = self.proposals()
        view.agents = list(self.slots)
        view.env = SimpleNamespace(task=self.task)
        view.domain = self.domain
        view.evidence_pack = copy.deepcopy(self.evidence_pack)
        return view

    def restore_result_inputs(self, result: Any) -> None:
        """Discard callback mutations to result fields that affect the tally."""
        if hasattr(result, "metadata"):
            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            if self.had_initial_process_verification:
                metadata["process_verification"] = copy.deepcopy(self.initial_process_verification)
            else:
                metadata.pop("process_verification", None)
            result.metadata = metadata
        if hasattr(result, "verification_results"):
            result.verification_results = copy.deepcopy(self.initial_verification_results)
        if hasattr(result, "verification_bonuses"):
            result.verification_bonuses = copy.deepcopy(self.initial_verification_bonuses)

    def resolve_slot_weights(self, ballots: tuple[SlotVote, ...]) -> tuple[float, ...]:
        """Resolve final exact-slot weights from frozen base factors and policy."""
        return self.vote_weight_policy.resolve_slot_weights(
            self.slots,
            self.base_slot_weights,
            ballots,
            self.proposals(),
        )

    def align_weights(self, weights_by_name: dict[str, float]) -> tuple[float, ...]:
        """Expand name-keyed legacy weights onto every exact voter slot."""
        weights: list[float] = []
        for slot in self.slots:
            raw_weight = weights_by_name.get(slot.name, 1.0)
            if (
                isinstance(raw_weight, bool)
                or not isinstance(raw_weight, (int, float))
                or not math.isfinite(raw_weight)
                or raw_weight < 0.0
            ):
                raise ValueError(f"Invalid vote weight for slot {slot.index}")
            weights.append(float(raw_weight))
        if weights and (not math.isfinite(sum(weights)) or sum(weights) <= 0.0):
            raise ValueError("Invalid aggregate voter weight")
        return tuple(weights)

    def decisive_leader(
        self,
        ballots: tuple[SlotVote, ...],
        *,
        minimum_collection_ratio: float,
        minimum_lead_ratio: float,
    ) -> tuple[bool, str | None]:
        """Return a winner only when no allocation of pending weight can overtake it."""
        weights = self.fixed_slot_weights
        if weights is None or not self.slots or not ballots:
            return False, None
        minimum_ballots = int(self.eligible_count * minimum_collection_ratio)
        if len(ballots) < minimum_ballots:
            return False, None

        seen_slots: set[int] = set()
        counts: dict[str, float] = {}
        received_weight = 0.0
        for ballot in ballots:
            slot_index = ballot.slot.index
            choice = getattr(ballot.vote, "choice", None)
            if (
                slot_index in seen_slots
                or slot_index < 0
                or slot_index >= self.eligible_count
                or self.slots[slot_index] != ballot.slot
                or not isinstance(choice, str)
                or not choice
            ):
                return False, None
            seen_slots.add(slot_index)
            weight = weights[slot_index]
            counts[choice] = counts.get(choice, 0.0) + weight
            received_weight += weight

        total_weight = sum(weights)
        leader, leader_weight = max(counts.items(), key=lambda item: item[1])
        runner_up = max(
            (weight for choice, weight in counts.items() if choice != leader), default=0.0
        )
        pending_weight = max(0.0, total_weight - received_weight)
        strongest_possible_competitor = runner_up + pending_weight
        if leader_weight / total_weight < self.effective_threshold:
            return False, None
        if leader_weight <= strongest_possible_competitor:
            return False, None
        if leader_weight - strongest_possible_competitor < total_weight * minimum_lead_ratio:
            return False, None
        return True, leader


class ConsensusPhase:
    """
    Executes the consensus resolution phase.

    This class encapsulates the voting and consensus logic that was
    previously in Arena._run_inner() after the debate rounds.

    Usage (new style with dataclasses):
        deps = ConsensusDependencies(
            protocol=arena.protocol,
            elo_system=arena.elo_system,
            memory=arena.memory,
        )
        callbacks = ConsensusCallbacks(
            vote_with_agent=arena._vote_with_agent,
        )
        consensus_phase = ConsensusPhase(deps, callbacks)
        await consensus_phase.execute(ctx)

    Usage (legacy style - backward compatible):
        consensus_phase = ConsensusPhase(
            protocol=arena.protocol,
            elo_system=arena.elo_system,
        )
        await consensus_phase.execute(ctx)
    """

    def __init__(
        self,
        deps: ConsensusDependencies | Any = None,
        callbacks: ConsensusCallbacks | None = None,
        # Legacy parameters for backward compatibility
        protocol: Any = None,
        elo_system: Any = None,
        memory: Any = None,
        agent_weights: dict[str, float] | None = None,
        flip_detector: Any = None,
        position_tracker: Any = None,
        calibration_tracker: Any = None,
        recorder: Any = None,
        hooks: dict | None = None,
        user_votes: list | None = None,
        # Legacy callbacks
        vote_with_agent: Callable | None = None,
        with_timeout: Callable | None = None,
        select_judge: Callable | None = None,
        build_judge_prompt: Callable | None = None,
        generate_with_agent: Callable | None = None,
        group_similar_votes: Callable | None = None,
        get_calibration_weight: Callable | None = None,
        notify_spectator: Callable | None = None,
        drain_user_events: Callable | None = None,
        extract_debate_domain: Callable | None = None,
        get_belief_analyzer: Callable | None = None,
        user_vote_multiplier: Callable | None = None,
        verify_claims: Callable | None = None,
    ):
        """
        Initialize the consensus phase.

        Args:
            deps: ConsensusDependencies dataclass (new style)
            callbacks: ConsensusCallbacks dataclass (new style)

            Legacy args (for backward compatibility):
            protocol, elo_system, memory, agent_weights, flip_detector,
            position_tracker, calibration_tracker, recorder, hooks, user_votes,
            and all callback parameters.
        """
        # Support both new dataclass style and legacy parameter style
        if isinstance(deps, ConsensusDependencies):
            # New style: use dataclasses
            self.protocol = deps.protocol
            self.elo_system = deps.elo_system
            self.memory = deps.memory
            self.agent_weights = deps.agent_weights
            self.flip_detector = deps.flip_detector
            self.position_tracker = deps.position_tracker
            self.calibration_tracker = deps.calibration_tracker
            self.recorder = deps.recorder
            self.hooks = deps.hooks
            self.user_votes = deps.user_votes
        else:
            # Legacy style: use individual parameters
            self.protocol = deps if deps is not None else protocol
            self.elo_system = elo_system
            self.memory = memory
            self.agent_weights = agent_weights or {}
            self.flip_detector = flip_detector
            self.position_tracker = position_tracker
            self.calibration_tracker = calibration_tracker
            self.recorder = recorder
            self.hooks = hooks or {}
            self.user_votes = user_votes or []

        # Callbacks: prefer dataclass, fall back to legacy parameters
        if callbacks is not None:
            self._vote_with_agent = callbacks.vote_with_agent
            self._with_timeout = callbacks.with_timeout
            self._select_judge = callbacks.select_judge
            self._build_judge_prompt = callbacks.build_judge_prompt
            self._generate_with_agent = callbacks.generate_with_agent
            self._group_similar_votes = callbacks.group_similar_votes
            self._get_calibration_weight = callbacks.get_calibration_weight
            self._notify_spectator = callbacks.notify_spectator
            self._drain_user_events = callbacks.drain_user_events
            self._extract_debate_domain = callbacks.extract_debate_domain
            self._get_belief_analyzer = callbacks.get_belief_analyzer
            self._user_vote_multiplier = callbacks.user_vote_multiplier
            self._verify_claims = callbacks.verify_claims
        else:
            self._vote_with_agent = vote_with_agent
            self._with_timeout = with_timeout
            self._select_judge = select_judge
            self._build_judge_prompt = build_judge_prompt
            self._generate_with_agent = generate_with_agent
            self._group_similar_votes = group_similar_votes
            self._get_calibration_weight = get_calibration_weight
            self._notify_spectator = notify_spectator
            self._drain_user_events = drain_user_events
            self._extract_debate_domain = extract_debate_domain
            self._get_belief_analyzer = get_belief_analyzer
            self._user_vote_multiplier = user_vote_multiplier
            self._verify_claims = verify_claims

        # Initialize helper classes
        self._winner_selector = WinnerSelector(
            protocol=self.protocol,
            position_tracker=self.position_tracker,
            calibration_tracker=self.calibration_tracker,
            recorder=self.recorder,
            notify_spectator=self._notify_spectator,
            extract_debate_domain=self._extract_debate_domain,
            get_belief_analyzer=self._get_belief_analyzer,
        )

        self._consensus_verifier = ConsensusVerifier(
            protocol=self.protocol,
            elo_system=self.elo_system,
            verify_claims=self._verify_claims,
            extract_debate_domain=self._extract_debate_domain,
        )

        self._synthesis_generator = SynthesisGenerator(
            protocol=self.protocol,
            hooks=self.hooks,
            notify_spectator=self._notify_spectator,
        )

        self._vote_bonus_calculator = VoteBonusCalculator(protocol=self.protocol)

        # Adaptive consensus threshold (opt-in via protocol flag)
        self._adaptive_consensus = None
        if getattr(self.protocol, "enable_adaptive_consensus", False):
            try:
                from aragora.debate.adaptive_consensus import (
                    AdaptiveConsensus,
                    AdaptiveConsensusConfig,
                )

                ac_config = AdaptiveConsensusConfig(
                    base_threshold=getattr(self.protocol, "consensus_threshold", 0.6),
                )
                self._adaptive_consensus = AdaptiveConsensus(ac_config)
            except ImportError:
                logger.debug("AdaptiveConsensus not available")

    # Default timeout for consensus phase (can be overridden via protocol)
    # Judge mode needs more time due to LLM generation latency
    DEFAULT_CONSENSUS_TIMEOUT = AGENT_TIMEOUT_SECONDS + 60  # Agent timeout + margin

    # Per-judge timeout for fallback retries
    JUDGE_TIMEOUT_PER_ATTEMPT = AGENT_TIMEOUT_SECONDS - 60

    # Outer timeout for collecting ALL votes
    VOTE_COLLECTION_TIMEOUT = AGENT_TIMEOUT_SECONDS + 60

    @property
    def _vote_collector(self) -> VoteCollector:
        """Lazy-initialized VoteCollector instance."""
        if not hasattr(self, "_vote_collector_instance"):
            # Get position shuffling config from protocol if available
            enable_position_shuffling = getattr(self.protocol, "enable_position_shuffling", False)
            position_shuffling_permutations = getattr(
                self.protocol, "position_shuffling_permutations", 3
            )

            # RLM early termination can be disabled via protocol
            enable_rlm_early_termination = getattr(
                self.protocol, "enable_rlm_early_termination", True
            )

            config = VoteCollectorConfig(
                vote_with_agent=self._vote_with_agent,
                with_timeout=self._with_timeout,
                notify_spectator=self._notify_spectator,
                hooks=self.hooks,
                recorder=self.recorder,
                position_tracker=self.position_tracker,
                group_similar_votes=self._group_similar_votes,
                vote_collection_timeout=self.VOTE_COLLECTION_TIMEOUT,
                agent_timeout=AGENT_TIMEOUT_SECONDS,
                # Agent-as-a-Judge position bias mitigation
                enable_position_shuffling=enable_position_shuffling,
                position_shuffling_permutations=position_shuffling_permutations,
                # RLM early termination
                enable_rlm_early_termination=enable_rlm_early_termination,
            )
            self._vote_collector_instance = VoteCollector(config)
        return self._vote_collector_instance

    async def execute(self, ctx: "DebateContext") -> None:
        """
        Execute the consensus phase with fallback mechanisms.

        This method wraps consensus execution with:
        - Timeout protection (default 120s)
        - Exception handling with fallback to 'none' mode
        - Graceful degradation when agents fail
        - GUARANTEED synthesis generation (never fails silently)

        Args:
            ctx: The DebateContext with proposals and result
        """
        # Check for cancellation before starting
        if ctx.cancellation_token and ctx.cancellation_token.is_cancelled:
            from aragora.debate.cancellation import DebateCancelled

            raise DebateCancelled(ctx.cancellation_token.reason or "Debate cancelled")

        # Trigger PRE_CONSENSUS hook if hook_manager is available
        if ctx.hook_manager:
            try:
                await ctx.hook_manager.trigger("pre_consensus", ctx=ctx, proposals=ctx.proposals)
            except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
                logger.debug("PRE_CONSENSUS hook failed: %s", e)

        consensus_mode = self.protocol.consensus if self.protocol else "none"
        logger.info("consensus_phase_start mode=%s", consensus_mode)

        # Get timeout from protocol or use default
        timeout = getattr(self.protocol, "consensus_timeout", self.DEFAULT_CONSENSUS_TIMEOUT)

        # Track consensus detection latency for SLO metrics
        consensus_start = time.perf_counter()

        try:
            await asyncio.wait_for(self._execute_consensus(ctx, consensus_mode), timeout=timeout)

            # Attempt formal verification if enabled and consensus reached
            if require_phase_result(ctx).consensus_reached:
                await self._verify_consensus_formally(ctx)

        except asyncio.TimeoutError:
            logger.warning(
                "consensus_timeout mode=%s timeout=%ss, falling back to none",
                consensus_mode,
                timeout,
            )
            await self._handle_fallback_consensus(ctx, reason="timeout")
        except CruxFinderDisabledError:
            raise
        except Exception as e:  # noqa: BLE001 - phase isolation
            category, msg, _ = _build_error_action(e, "consensus")
            logger.error(
                "consensus_error mode=%s category=%s error=%s",
                consensus_mode,
                category,
                msg,
                exc_info=True,
            )
            await self._handle_fallback_consensus(ctx, reason="error: %s" % type(e).__name__)
        finally:
            # Record consensus detection latency for SLO tracking (p50/p95/p99)
            consensus_latency = time.perf_counter() - consensus_start
            record_consensus_detection_latency(consensus_latency, consensus_mode)

        # Crux cards (#8227 phase 1): attach load-bearing disagreements to the
        # result metadata for receipt export. Runs regardless of consensus
        # outcome — cruxes matter most when consensus was NOT reached.
        if getattr(self.protocol, "enable_crux_cards", False):
            self._attach_crux_cards(ctx)

        # Always generate final synthesis regardless of consensus mode
        try:
            synthesis_generated = await self._synthesis_generator.generate_mandatory_synthesis(ctx)

            if not synthesis_generated:
                logger.error("synthesis_failed_all_fallbacks - this should not happen")
                if ctx.proposals:
                    fallback_synthesis = (
                        f"## Debate Summary\n\n{list(ctx.proposals.values())[0][:1000]}"
                    )
                    fallback_result = require_phase_result(ctx)
                    fallback_result.synthesis = fallback_synthesis
                    fallback_result.final_answer = fallback_synthesis
                    try:
                        if self.hooks and "on_message" in self.hooks:
                            self.hooks["on_message"](
                                agent="synthesis-agent",
                                content=fallback_synthesis,
                                role="synthesis",
                                round_num=(self.protocol.rounds if self.protocol else 3) + 1,
                            )
                    except (RuntimeError, AttributeError, TypeError) as hook_err:  # noqa: BLE001 - phase isolation
                        logger.warning("on_message hook failed in fallback: %s", hook_err)
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.error("synthesis_or_hooks_failed: %s", e, exc_info=True)
        finally:
            logger.info("consensus_phase_emitting_guaranteed_events")
            self._emit_guaranteed_events(ctx)

    def _attach_crux_cards(self, ctx: "DebateContext") -> None:
        """Attach a crux-cards block to result metadata (``enable_crux_cards``).

        Best-effort enrichment: any failure is logged and swallowed so it can
        never break the consensus phase. When nothing is detected, the result
        is left untouched (flag-off receipts stay byte-identical).
        """
        try:
            from aragora.debate.crux_cards import CRUX_CARDS_METADATA_KEY, build_crux_cards

            result = require_phase_result(ctx)
            cards = build_crux_cards(
                belief_network=getattr(ctx, "belief_network", None),
                messages=list(result.messages or []),
                # Without these the network has no factor edges, so the crux
                # detector sees zero disagreements and can never emit a card
                # however contested the debate was (#9581).
                critiques=list(result.critiques or []),
                top_k=int(getattr(self.protocol, "crux_finder_top_k", 5) or 5),
                min_score=float(getattr(self.protocol, "crux_finder_min_score", 0.3) or 0.3),
            )
            if cards:
                result.metadata[CRUX_CARDS_METADATA_KEY] = cards
                logger.info("crux_cards_attached count=%d", len(cards["items"]))
        except (
            RuntimeError,
            AttributeError,
            ImportError,
            TypeError,
            ValueError,
            KeyError,
        ) as e:
            logger.warning("crux_cards_failed: %s", e)

    def _emit_guaranteed_events(self, ctx: "DebateContext") -> None:
        """Emit consensus and debate_end events with guaranteed delivery."""
        if not ctx.result:
            return

        # Trigger POST_CONSENSUS hook if hook_manager is available
        if ctx.hook_manager:
            try:
                # Use asyncio.create_task for async hook in sync method
                import asyncio

                try:
                    asyncio.get_running_loop()
                    _hook_task = asyncio.create_task(
                        ctx.hook_manager.trigger(
                            "post_consensus",
                            ctx=ctx,
                            result=ctx.result,
                            consensus_reached=ctx.result.consensus_reached,
                        )
                    )
                    _hook_task.add_done_callback(
                        lambda t: logger.warning("POST_CONSENSUS hook failed: %s", t.exception())
                        if not t.cancelled() and t.exception()
                        else None
                    )
                except RuntimeError:
                    logger.debug("No running event loop for POST_CONSENSUS hook")
            except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
                logger.debug("POST_CONSENSUS hook failed: %s", e)

        if self.hooks and "on_consensus" in self.hooks:
            try:
                self.hooks["on_consensus"](
                    reached=ctx.result.consensus_reached,
                    confidence=ctx.result.confidence,
                    answer=ctx.result.final_answer,
                    synthesis=ctx.result.synthesis or "",
                )
                logger.debug("consensus_event_emitted reached=%s", ctx.result.consensus_reached)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001 - phase isolation
                logger.warning("Failed to emit consensus event: %s", e)

        if self.hooks and "on_debate_end" in self.hooks:
            try:
                duration = time.time() - ctx.start_time if hasattr(ctx, "start_time") else 0.0
                self.hooks["on_debate_end"](
                    duration=duration,
                    rounds=ctx.result.rounds_used,
                )
                logger.debug("debate_end_event_emitted duration=%.1fs", duration)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001 - phase isolation
                logger.warning("Failed to emit debate_end event: %s", e)

    async def _execute_consensus(self, ctx: "DebateContext", consensus_mode: str) -> None:
        """Execute the consensus logic for the given mode."""
        normalized = consensus_mode
        threshold_override: float | None = None

        if consensus_mode == "weighted":
            normalized = "majority"
        elif consensus_mode == "hybrid":
            # "hybrid" combines voting with judge adjudication; consensus phase already
            # performs vote collection before mode dispatch, so route to judge finalization.
            normalized = "judge"
        elif consensus_mode == "supermajority":
            normalized = "majority"
            threshold_override = max(getattr(self.protocol, "consensus_threshold", 0.6), 2 / 3)
        elif consensus_mode == "any":
            normalized = "majority"
            threshold_override = 0.0

        if normalized == "none":
            await self._handle_none_consensus(ctx)
        elif normalized == "majority":
            await self._handle_majority_consensus(ctx, threshold_override=threshold_override)
        elif normalized == "unanimous":
            await self._handle_unanimous_consensus(ctx)
        elif normalized == "judge":
            await self._handle_judge_consensus(ctx)
        elif normalized == "byzantine":
            await self._handle_byzantine_consensus(ctx)
        elif consensus_mode == "prover_estimator":
            await self._handle_prover_estimator_consensus(ctx)
        elif consensus_mode == "crux_finder":
            await self._handle_crux_finder_consensus(ctx)
        else:
            logger.warning("Unknown consensus mode: %s, using none", consensus_mode)
            await self._handle_none_consensus(ctx)

    async def _handle_fallback_consensus(self, ctx: "DebateContext", reason: str) -> None:
        """Handle consensus fallback when the primary mechanism fails."""
        result = require_phase_result(ctx)
        proposals = ctx.proposals

        logger.info("consensus_fallback reason=%s proposals=%s", reason, len(proposals))

        winner_agent = None
        winner_confidence = 0.0

        if result.votes:
            vote_counts: dict[str, int] = {}
            for vote in result.votes:
                if hasattr(vote, "choice") and vote.choice:
                    vote_counts[vote.choice] = vote_counts.get(vote.choice, 0) + 1
            if vote_counts:
                winner_agent = max(vote_counts.items(), key=lambda x: x[1])[0]
                total_votes = sum(vote_counts.values())
                winner_confidence = (
                    vote_counts[winner_agent] / total_votes if total_votes > 0 else 0.0
                )
                logger.info(
                    "consensus_fallback_winner_from_votes winner=%s confidence=%s",
                    winner_agent,
                    winner_confidence,
                )

        if not winner_agent and ctx.vote_tally:
            winner_agent = max(ctx.vote_tally.items(), key=lambda x: x[1])[0]
            tally_total = sum(ctx.vote_tally.values())
            winner_confidence = (
                ctx.vote_tally[winner_agent] / tally_total if tally_total > 0 else 0.5
            )
            logger.info(
                "consensus_fallback_winner_from_tally winner=%s confidence=%s",
                winner_agent,
                winner_confidence,
            )

        if winner_agent:
            ctx.winner_agent = winner_agent
            result.winner = winner_agent
            result.confidence = winner_confidence
            if winner_agent in proposals:
                result.final_answer = proposals[winner_agent]
            else:
                result.final_answer = (
                    f"[Consensus fallback ({reason}) - Winner: {winner_agent}]\n\n"
                    + "\n\n---\n\n".join(f"[{agent}]:\n{prop}" for agent, prop in proposals.items())
                )
            result.consensus_reached = True
            result.consensus_strength = "fallback"
        else:
            if proposals:
                result.final_answer = f"[Consensus fallback ({reason})]\n\n" + "\n\n---\n\n".join(
                    f"[{agent}]:\n{prop}" for agent, prop in proposals.items()
                )
            else:
                result.final_answer = f"[No proposals available - consensus fallback ({reason})]"
            result.consensus_reached = False
            result.confidence = 0.5
            result.consensus_strength = "fallback"

        logger.info("consensus_fallback reason=%s winner=%s", reason, winner_agent)

    async def _handle_none_consensus(self, ctx: "DebateContext") -> None:
        """Handle 'none' consensus mode - combine all proposals."""
        result = require_phase_result(ctx)
        proposals = ctx.proposals

        if proposals:
            result.final_answer = "\n\n---\n\n".join(
                f"[{agent}]:\n{prop}" for agent, prop in proposals.items()
            )
        else:
            result.final_answer = "[No proposals available - consensus mode 'none']"
        result.consensus_reached = False
        result.confidence = 0.5

    async def _handle_majority_consensus(
        self,
        ctx: "DebateContext",
        threshold_override: float | None = None,
    ) -> None:
        """Handle 'majority' consensus mode - weighted voting."""
        result = require_phase_result(ctx)
        eligible_agents = tuple(ctx.agents)

        # User-event ingestion is part of the decision boundary. Anything that
        # arrives after this synchronous drain belongs to a later decision.
        if self._drain_user_events:
            self._drain_user_events()

        # Compute adaptive threshold when enabled and no explicit override
        if threshold_override is None and self._adaptive_consensus is not None:
            try:
                threshold_override, explanation = (
                    self._adaptive_consensus.compute_threshold_with_explanation(
                        list(eligible_agents),
                        elo_system=self.elo_system,
                        calibration_tracker=self.calibration_tracker,
                    )
                )
                # Store explanation in result metadata for audit trail
                if (
                    ctx.result
                    and hasattr(ctx.result, "metadata")
                    and isinstance(ctx.result.metadata, dict)
                ):
                    ctx.result.metadata["adaptive_threshold_explanation"] = explanation
                logger.info(
                    "adaptive_consensus_threshold=%.4f for %d agents",
                    threshold_override,
                    len(eligible_agents),
                )
            except (TypeError, ValueError, AttributeError) as e:
                logger.debug("Adaptive consensus computation failed: %s", e)
                threshold_override = None

        effective_threshold = (
            threshold_override
            if threshold_override is not None
            else getattr(self.protocol, "consensus_threshold", 0.5)
        )
        min_participation_ratio = getattr(self.protocol, "min_participation_ratio", 0.5)
        min_participation_count = getattr(self.protocol, "min_participation_count", 1)

        # Capture every decision input before the first voter callback can run.
        decision_protocol = copy.deepcopy(self.protocol)
        frozen_proposals = copy.deepcopy(ctx.proposals)
        frozen_task = str(ctx.env.task if ctx.env else "")
        frozen_domain = str(getattr(ctx, "domain", None) or "general")
        collector = self._vote_collector
        collector_config = collector.config
        position_shuffling_enabled = bool(collector_config.enable_position_shuffling)
        position_shuffling_permutations = int(collector_config.position_shuffling_permutations)
        position_shuffling_seed = collector_config.position_shuffling_seed
        effective_agent_timeout = get_complexity_governor().get_scaled_timeout(
            float(collector_config.agent_timeout)
        )
        collection_timeout = float(collector_config.vote_collection_timeout)
        rlm_early_termination_enabled = bool(collector_config.enable_rlm_early_termination)
        rlm_early_termination_threshold = float(collector_config.rlm_early_termination_threshold)
        rlm_majority_lead_threshold = float(collector_config.rlm_majority_lead_threshold)
        user_vote_contributions = self._capture_user_vote_contributions(decision_protocol)
        provisional_slots = tuple(
            VoterSlot(index=index, name=str(getattr(agent, "name", "")))
            for index, agent in enumerate(eligible_agents)
        )
        calibration_summaries = self._capture_calibration_summaries(provisional_slots)
        base_weights_by_name = self._compute_vote_weights(
            ctx,
            agents=eligible_agents,
            protocol=decision_protocol,
            proposals=frozen_proposals,
            domain=frozen_domain,
        )
        tally_inputs_fixed = self._rlm_tally_inputs_are_fixed(
            protocol=decision_protocol,
            user_vote_contributions=user_vote_contributions,
            group_similar_votes=self._group_similar_votes,
            position_shuffling_enabled=position_shuffling_enabled,
        )
        majority_snapshot = _MajoritySnapshot.capture(
            effective_threshold=effective_threshold,
            agents=eligible_agents,
            min_participation_ratio=min_participation_ratio,
            min_participation_count=min_participation_count,
            proposals=frozen_proposals,
            protocol=decision_protocol,
            task=frozen_task,
            domain=frozen_domain,
            base_weights_by_name=base_weights_by_name,
            tally_inputs_fixed=tally_inputs_fixed,
            user_vote_contributions=user_vote_contributions,
            calibration_summaries=calibration_summaries,
            evidence_pack=getattr(ctx, "evidence_pack", None),
            result=result,
            group_similar_votes=self._group_similar_votes,
            verify_claims=self._verify_claims,
            position_shuffling_enabled=position_shuffling_enabled,
            position_shuffling_permutations=position_shuffling_permutations,
            position_shuffling_seed=position_shuffling_seed,
            agent_timeout=effective_agent_timeout,
            collection_timeout=collection_timeout,
            rlm_early_termination_enabled=rlm_early_termination_enabled,
            rlm_early_termination_threshold=rlm_early_termination_threshold,
            rlm_majority_lead_threshold=rlm_majority_lead_threshold,
        )
        roster = tuple(zip(majority_snapshot.slots, eligible_agents, strict=True))

        should_stop = None
        if (
            majority_snapshot.rlm_early_termination_enabled
            and majority_snapshot.fixed_slot_weights is not None
        ):

            def should_stop(ballots: tuple[SlotVote, ...]) -> tuple[bool, str | None]:
                return majority_snapshot.decisive_leader(
                    ballots,
                    minimum_collection_ratio=majority_snapshot.rlm_early_termination_threshold,
                    minimum_lead_ratio=majority_snapshot.rlm_majority_lead_threshold,
                )

        decision_ctx = majority_snapshot.make_context_view(ctx)
        collection = await collector.collect_majority_votes(
            decision_ctx,
            roster,
            proposals=majority_snapshot.proposals(),
            should_stop=should_stop,
            position_shuffling_enabled=majority_snapshot.position_shuffling_enabled,
            position_shuffling_permutations=(majority_snapshot.position_shuffling_permutations),
            position_shuffling_seed=majority_snapshot.position_shuffling_seed,
            agent_timeout=majority_snapshot.agent_timeout,
            collection_timeout=majority_snapshot.collection_timeout,
        )
        majority_snapshot.restore_result_inputs(result)
        self._record_vote_participation(ctx, collection, majority_snapshot)
        if not self._ensure_quorum(
            decision_ctx,
            len(collection.ballots),
            required=majority_snapshot.required_participation,
            total_agents=majority_snapshot.eligible_count,
        ):
            return

        # Apply calibration adjustments to vote confidences
        votes = self._apply_calibration_to_votes(
            copy.deepcopy(collection.votes),
            decision_ctx,
            calibration_summaries=majority_snapshot.calibration_summary_map(),
        )
        ballots = tuple(
            replace(ballot, vote=vote)
            for ballot, vote in zip(collection.ballots, votes, strict=True)
        )

        result.votes.extend(votes)

        # Group similar votes
        vote_groups, choice_mapping = self._compute_vote_groups(
            copy.deepcopy(votes),
            group_similar_votes=majority_snapshot.group_similar_votes,
        )

        # Vote-dependent bias factors are resolved against captured base
        # weights, policy scalars, exact slots, and frozen proposals only.
        slot_weights = majority_snapshot.resolve_slot_weights(ballots)

        # Missing, failed, and early-stopped slots remain in the denominator.
        vote_counts, total_weighted = self._count_snapshot_votes(
            ballots,
            choice_mapping,
            slot_weights,
        )

        # Include user votes
        vote_counts, total_weighted = self._add_snapshot_user_votes(
            vote_counts,
            total_weighted,
            choice_mapping,
            majority_snapshot.user_vote_contributions,
        )

        consensus_verifier = ConsensusVerifier(
            protocol=majority_snapshot.protocol,
            elo_system=self.elo_system,
            verify_claims=majority_snapshot.verify_claims,
            extract_debate_domain=self._extract_debate_domain,
        )
        vote_bonus_calculator = VoteBonusCalculator(protocol=majority_snapshot.protocol)
        winner_selector = WinnerSelector(
            protocol=majority_snapshot.protocol,
            position_tracker=self.position_tracker,
            calibration_tracker=self.calibration_tracker,
            recorder=self.recorder,
            notify_spectator=self._notify_spectator,
            extract_debate_domain=self._extract_debate_domain,
            get_belief_analyzer=self._get_belief_analyzer,
        )
        proposals = majority_snapshot.proposals()

        # Apply verification bonuses if enabled
        vote_counts = await consensus_verifier.apply_verification_bonuses(
            decision_ctx, vote_counts, proposals, choice_mapping
        )

        # Adjust individual vote confidences based on verification results
        # This cross-pollinates formal verification with vote confidence
        if hasattr(result, "verification_results") and result.verification_results:
            consensus_verifier.adjust_vote_confidence_from_verification(
                votes, result.verification_results, proposals
            )

        # Apply evidence citation bonuses if enabled
        vote_counts = vote_bonus_calculator.apply_evidence_citation_bonuses(
            decision_ctx, votes, vote_counts, choice_mapping
        )

        # Apply process-based evaluation bonuses if enabled (Agent-as-a-Judge)
        vote_counts = await vote_bonus_calculator.apply_process_evaluation_bonuses(
            decision_ctx, vote_counts, choice_mapping
        )

        # Apply epistemic hygiene penalties if enabled
        vote_counts = vote_bonus_calculator.apply_epistemic_hygiene_penalties(
            decision_ctx, vote_counts, choice_mapping
        )

        # Apply truth ratio bonuses if enabled
        vote_counts = vote_bonus_calculator.apply_truth_ratio_bonuses(
            decision_ctx, vote_counts, choice_mapping
        )

        ctx.vote_tally = dict(vote_counts)
        decision_ctx.vote_tally = dict(vote_counts)

        # Determine winner using WinnerSelector
        winner_selector.determine_majority_winner(
            decision_ctx,
            vote_counts,
            total_weighted,
            choice_mapping,
            normalize_choice=lambda choice, _agents, current_proposals: (
                self._normalize_choice_to_names(
                    choice,
                    majority_snapshot.agent_names,
                    majority_snapshot.proposals(),
                )
            ),
            threshold_override=majority_snapshot.effective_threshold,
        )
        ctx.winner_agent = decision_ctx.winner_agent

        # Apply process verification gate if enabled
        self._apply_process_verification_gate(
            decision_ctx,
            protocol=majority_snapshot.protocol,
        )

        # Analyze belief network for cruxes
        winner_selector.analyze_belief_network(decision_ctx)

    async def _handle_unanimous_consensus(self, ctx: "DebateContext") -> None:
        """Handle 'unanimous' consensus mode - all must agree."""
        result = require_phase_result(ctx)
        proposals = ctx.proposals

        votes, voting_errors = await self._collect_votes_with_errors(ctx)
        if not self._ensure_quorum(ctx, len(votes)):
            return
        votes = self._apply_calibration_to_votes(votes, ctx)
        result.votes.extend(votes)

        vote_groups, choice_mapping = self._compute_vote_groups(votes)

        vote_counts: Counter[str] = Counter()
        for v in votes:
            if not isinstance(v, Exception):
                canonical = choice_mapping.get(v.choice, v.choice)
                vote_counts[canonical] += 1

        if self._drain_user_events:
            self._drain_user_events()

        user_vote_weight = getattr(self.protocol, "user_vote_weight", 0.0)
        user_vote_count = 0
        if user_vote_weight > 0:
            for user_vote in self.user_votes:
                choice = user_vote.get("choice", "")
                if choice:
                    canonical = choice_mapping.get(choice, choice)
                    vote_counts[canonical] += 1
                    user_vote_count += 1
                    logger.debug(
                        "user_vote_unanimous user=%s choice=%s",
                        user_vote.get("user_id", "anonymous"),
                        choice,
                    )

        ctx.vote_tally = dict(vote_counts)

        total_voters = len(votes) + user_vote_count + voting_errors
        if voting_errors > 0:
            logger.info("unanimous_vote_errors counted_as_dissent=%s", voting_errors)

        most_common = vote_counts.most_common(1) if vote_counts else []
        if most_common and total_voters > 0:
            winner, count = most_common[0]
            unanimity_ratio = count / total_voters

            if unanimity_ratio >= 1.0:
                self._winner_selector.set_unanimous_winner(
                    ctx, winner, unanimity_ratio, total_voters, count
                )
            else:
                self._winner_selector.set_no_unanimity(
                    ctx, winner, unanimity_ratio, total_voters, count, choice_mapping
                )
        else:
            result.final_answer = list(proposals.values())[0] if proposals else ""
            result.consensus_reached = False
            result.confidence = 0.5

    def _apply_process_verification_gate(
        self,
        ctx: "DebateContext",
        *,
        protocol: Any | None = None,
    ) -> None:
        """Gate consensus based on process verification scores."""
        decision_protocol = self.protocol if protocol is None else protocol
        if not decision_protocol or not getattr(
            decision_protocol, "enable_process_verification", False
        ):
            return
        result = require_phase_result(ctx)
        if not result or not result.metadata:
            return
        metadata = result.metadata.get("process_verification", {})
        average = metadata.get("average")
        if average is None:
            return

        threshold = float(getattr(decision_protocol, "process_verification_threshold", 0.6))
        metadata["threshold"] = threshold
        metadata["passed"] = average >= threshold

        if not metadata["passed"] and getattr(
            decision_protocol, "process_verification_hard_gate", False
        ):
            result.consensus_reached = False
            result.consensus_strength = "process_blocked"
            result.status = "process_verification_failed"

    async def _handle_judge_consensus(self, ctx: "DebateContext") -> None:
        """Handle 'judge' consensus mode - single judge synthesis with fallback."""
        result = require_phase_result(ctx)
        proposals = ctx.proposals

        if not self._select_judge or not self._generate_with_agent:
            logger.error("Judge consensus requires select_judge and generate_with_agent")
            result.final_answer = list(proposals.values())[0] if proposals else ""
            result.consensus_reached = False
            result.confidence = 0.5
            return

        # Check for judge deliberation mode (Agent-as-a-Judge enhancement)
        enable_deliberation = getattr(self.protocol, "enable_judge_deliberation", False)
        if enable_deliberation:
            await self._handle_judge_deliberation(ctx)
            return

        judge_method = self.protocol.judge_selection if self.protocol else "random"
        task = ctx.env.task if ctx.env else ""

        judge_prompt = (
            self._build_judge_prompt(proposals, task, result.critiques)
            if self._build_judge_prompt
            else f"Synthesize these proposals: {proposals}"
        )

        judge_candidates = []
        if hasattr(self._select_judge, "__self__") and hasattr(
            self._select_judge.__self__, "get_judge_candidates"
        ):
            try:
                judge_candidates = await self._select_judge.__self__.get_judge_candidates(
                    proposals, ctx.context_messages, max_candidates=3
                )
            except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
                logger.debug("Failed to get judge candidates: %s", e)

        if not judge_candidates:
            judge = await self._select_judge(proposals, ctx.context_messages)
            judge_candidates = [judge] if judge else []

        tried_judges = []
        for judge in judge_candidates:
            if judge is None:
                continue

            judge_timeout = float(getattr(judge, "timeout", AGENT_TIMEOUT_SECONDS))
            judge_timeout = max(60.0, judge_timeout - 60.0)

            tried_judges.append(judge.name)
            logger.info(
                "judge_attempt judge=%s method=%s attempt=%s",
                judge.name,
                judge_method,
                len(tried_judges),
            )

            if self._notify_spectator:
                self._notify_spectator(
                    "judge",
                    agent=judge.name,
                    details=f"Selected as judge via {judge_method}"
                    + (f" (attempt {len(tried_judges)})" if len(tried_judges) > 1 else ""),
                )

            if "on_judge_selected" in self.hooks:
                self.hooks["on_judge_selected"](judge.name, judge_method)

            try:
                task_id = f"{judge.name}:judge_synthesis"
                with streaming_task_context(task_id):
                    synthesis = await asyncio.wait_for(
                        self._generate_with_agent(judge, judge_prompt, ctx.context_messages),
                        timeout=judge_timeout,
                    )

                result.final_answer = synthesis
                result.consensus_reached = True
                result.confidence = 0.8
                ctx.winner_agent = judge.name
                result.winner = judge.name

                logger.info(
                    "judge_synthesis judge=%s length=%s attempts=%s",
                    judge.name,
                    len(synthesis),
                    len(tried_judges),
                )

                if self._notify_spectator:
                    self._notify_spectator(
                        "consensus",
                        agent=judge.name,
                        details=f"Judge synthesis ({len(synthesis)} chars)",
                        metric=0.8,
                    )

                if "on_message" in self.hooks:
                    rounds = self.protocol.rounds if self.protocol else 0
                    self.hooks["on_message"](
                        agent=judge.name,
                        content=synthesis,
                        role="judge",
                        round_num=rounds + 1,
                    )

                return

            except asyncio.TimeoutError:
                logger.warning("judge_timeout judge=%s timeout=%ss", judge.name, judge_timeout)
            except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
                logger.error("judge_error judge=%s error=%s: %s", judge.name, type(e).__name__, e)

        logger.warning("judge_all_failed tried=%s falling back to majority voting", tried_judges)

        try:
            await self._handle_majority_consensus(ctx)
            if result.consensus_reached:
                logger.info("judge_fallback_majority_success")
                return
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.warning("judge_fallback_majority_failed error=%s", e)

        await self._handle_fallback_consensus(ctx, reason="judge_and_majority_failed")

    async def _handle_judge_deliberation(self, ctx: "DebateContext") -> None:
        """Handle judge consensus with deliberation (Agent-as-a-Judge).

        Multiple judges deliberate on proposals before rendering verdict.
        This reduces individual biases by exposing judges to diverse perspectives.
        """
        from aragora.debate.judge_selector import (
            JudgingStrategy,
            JudgeVote,
            create_judge_panel,
        )

        result = require_phase_result(ctx)
        proposals = ctx.proposals
        task = ctx.env.task if ctx.env else ""
        select_judge = self._select_judge
        generate_with_agent = self._generate_with_agent

        if select_judge is None or generate_with_agent is None:
            logger.error("Judge deliberation requires select_judge and generate_with_agent")
            await self._handle_fallback_consensus(ctx, reason="judge_callbacks_missing")
            return

        deliberation_rounds = getattr(self.protocol, "judge_deliberation_rounds", 2)

        logger.info(
            "judge_deliberation_start proposals=%s rounds=%s",
            len(proposals),
            deliberation_rounds,
        )

        # Get judge candidates (use 3 judges for deliberation)
        judge_candidates = []
        select_judge_owner = getattr(select_judge, "__self__", None)
        if select_judge_owner is not None and hasattr(select_judge_owner, "get_judge_candidates"):
            try:
                judge_candidates = await select_judge_owner.get_judge_candidates(
                    proposals, ctx.context_messages, max_candidates=3
                )
            except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
                logger.debug("Failed to get judge candidates: %s", e)

        if not judge_candidates or len(judge_candidates) < 2:
            # Not enough judges for deliberation, fall back to single judge
            logger.warning("judge_deliberation_insufficient_judges falling_back_to_single")
            # Continue with regular judge consensus (without deliberation)
            judge = judge_candidates[0] if judge_candidates else None
            if judge:
                await self._run_single_judge_synthesis(ctx, judge)
            else:
                await self._handle_fallback_consensus(ctx, reason="no_judges_available")
            return

        # Create judge panel
        panel = create_judge_panel(
            candidates=judge_candidates,
            participants=ctx.agents,
            domain="debate_deliberation",
            strategy=JudgingStrategy.MAJORITY,
            count=min(3, len(judge_candidates)),
            elo_system=self.elo_system,
            exclude_participants=True,
        )

        if self._notify_spectator:
            self._notify_spectator(
                "judge_deliberation",
                details=f"Starting deliberation with {len(panel.judges)} judges",
                agent="system",
            )

        try:
            # Run deliberation
            deliberation_result = await panel.deliberate_and_vote(
                proposals=proposals,
                task=task,
                context=ctx.context_messages,
                generate_fn=generate_with_agent,
                deliberation_rounds=deliberation_rounds,
            )

            logger.info(
                "judge_deliberation_result approved=%s confidence=%s approval_ratio=%s",
                deliberation_result.approved,
                deliberation_result.confidence,
                deliberation_result.approval_ratio,
            )

            # If judges approve, use the best proposal as synthesis
            if deliberation_result.approved and proposals:
                # Pick proposal with highest approval from judges
                best_proposal_name = max(
                    proposals.keys(),
                    key=lambda k: sum(
                        1 for v in deliberation_result.votes if v.vote == JudgeVote.APPROVE
                    ),
                )
                result.final_answer = proposals[best_proposal_name]
                result.consensus_reached = True
                result.confidence = deliberation_result.confidence
                ctx.winner_agent = best_proposal_name
                result.winner = best_proposal_name

                if self._notify_spectator:
                    self._notify_spectator(
                        "consensus",
                        agent="judge_panel",
                        details=f"Deliberation approved: {best_proposal_name}",
                        metric=deliberation_result.confidence,
                    )
            else:
                # Judges rejected or need more debate
                logger.info("judge_deliberation_rejected continuing to synthesis")
                # Fall back to single judge synthesis
                judge = panel.judges[0] if panel.judges else None
                if judge:
                    await self._run_single_judge_synthesis(ctx, judge)
                else:
                    await self._handle_fallback_consensus(ctx, reason="deliberation_rejected")

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.error("judge_deliberation_error: %s", e)
            await self._handle_fallback_consensus(ctx, reason="deliberation_error")

    async def _run_single_judge_synthesis(self, ctx: "DebateContext", judge) -> None:
        """Run single judge synthesis (helper for deliberation fallback)."""
        result = require_phase_result(ctx)
        proposals = ctx.proposals
        task = ctx.env.task if ctx.env else ""
        generate_with_agent = self._generate_with_agent

        if generate_with_agent is None:
            logger.error("Judge synthesis requires generate_with_agent")
            await self._handle_fallback_consensus(ctx, reason="synthesis_callbacks_missing")
            return

        judge_prompt = (
            self._build_judge_prompt(proposals, task, result.critiques)
            if self._build_judge_prompt
            else f"Synthesize these proposals: {proposals}"
        )

        try:
            judge_timeout = float(getattr(judge, "timeout", AGENT_TIMEOUT_SECONDS))
            judge_timeout = max(60.0, judge_timeout - 60.0)
            task_id = f"{judge.name}:judge_synthesis"
            with streaming_task_context(task_id):
                synthesis = await asyncio.wait_for(
                    generate_with_agent(judge, judge_prompt, ctx.context_messages),
                    timeout=judge_timeout,
                )

            result.final_answer = synthesis
            result.consensus_reached = True
            result.confidence = 0.8
            ctx.winner_agent = judge.name
            result.winner = judge.name

            if self._notify_spectator:
                self._notify_spectator(
                    "consensus",
                    agent=judge.name,
                    details=f"Judge synthesis ({len(synthesis)} chars)",
                    metric=0.8,
                )

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.error("single_judge_synthesis_error judge=%s: %s", judge.name, e)
            await self._handle_fallback_consensus(ctx, reason="synthesis_error")

    async def _handle_byzantine_consensus(self, ctx: "DebateContext") -> None:
        """Handle 'byzantine' consensus mode - PBFT-style fault-tolerant consensus.

        Uses Byzantine Fault-Tolerant consensus protocol adapted from claude-flow.
        Tolerates up to f faulty (adversarial/hallucinating) agents where n >= 3f+1.

        PBFT Phases:
        1. PRE_PREPARE: Leader proposes a synthesis
        2. PREPARE: Agents validate and signal readiness
        3. COMMIT: Agents commit if 2f+1 prepare messages received
        """
        from aragora.debate.byzantine import (
            ByzantineConsensus,
            ByzantineConsensusConfig,
        )

        result = require_phase_result(ctx)
        proposals = ctx.proposals
        agents = ctx.agents

        if len(agents) < 4:
            logger.warning(
                "Byzantine consensus requires at least 4 agents, got %s. "
                "Falling back to majority voting.",
                len(agents),
            )
            await self._handle_majority_consensus(ctx)
            return

        # Build configuration from protocol settings
        config = ByzantineConsensusConfig(
            max_faulty_fraction=getattr(self.protocol, "byzantine_fault_tolerance", 0.33),
            phase_timeout_seconds=getattr(self.protocol, "byzantine_phase_timeout", 30.0),
            max_view_changes=getattr(self.protocol, "byzantine_max_view_changes", 3),
            min_agents=4,
        )

        # Create Byzantine consensus protocol
        protocol = ByzantineConsensus(agents=agents, config=config)

        # Build proposal from best proposal or synthesis
        if proposals:
            # Use the first proposal as the base for consensus
            # In a full implementation, we might synthesize or select the best
            proposal_agent = list(proposals.keys())[0]
            proposal_text = proposals[proposal_agent]
        else:
            logger.warning("No proposals available for Byzantine consensus")
            await self._handle_fallback_consensus(ctx, reason="no_proposals")
            return

        task = ctx.env.task if ctx.env else ""

        logger.info(
            "byzantine_consensus_start agents=%s quorum=%s f=%s",
            len(agents),
            protocol.quorum_size,
            protocol.f,
        )

        if self._notify_spectator:
            self._notify_spectator(
                "byzantine_consensus",
                details=f"Starting PBFT with {len(agents)} agents (f={protocol.f})",
            )

        try:
            # Run Byzantine consensus
            byz_result = await protocol.propose(proposal_text, task=task)

            if byz_result.success:
                result.final_answer = byz_result.value or proposal_text
                result.consensus_reached = True
                result.confidence = byz_result.confidence
                result.consensus_strength = "byzantine"

                # Store Byzantine-specific metadata in formal_verification field
                # (reusing this dict[str, Any] | None field for consensus metadata)
                if result.formal_verification is None:
                    result.formal_verification = {}
                result.formal_verification["byzantine_consensus"] = {
                    "view": byz_result.view,
                    "sequence": byz_result.sequence,
                    "commit_count": byz_result.commit_count,
                    "total_agents": byz_result.total_agents,
                    "agreement_ratio": byz_result.agreement_ratio,
                    "duration_seconds": byz_result.duration_seconds,
                }

                logger.info(
                    "byzantine_consensus_success view=%s commits=%s/%s confidence=%s",
                    byz_result.view,
                    byz_result.commit_count,
                    byz_result.total_agents,
                    byz_result.confidence,
                )

                if self._notify_spectator:
                    self._notify_spectator(
                        "consensus",
                        details=f"Byzantine consensus reached ({byz_result.commit_count}/{byz_result.total_agents} commits)",
                        metric=byz_result.confidence,
                    )
            else:
                logger.warning("byzantine_consensus_failed reason=%s", byz_result.failure_reason)
                # Fall back to majority voting
                await self._handle_majority_consensus(ctx)

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.error("byzantine_consensus_error: %s", e, exc_info=True)
            # Fall back to majority voting
            await self._handle_majority_consensus(ctx)

    async def _handle_prover_estimator_consensus(self, ctx: "DebateContext") -> None:
        """Handle 'prover_estimator' consensus — structured truth-seeking protocol.

        Uses the Prover-Estimator framework where claims are decomposed into
        subclaims, probability-estimated, challenged with evidence, and aggregated
        using importance-weighted geometric mean.
        """
        from aragora.debate.prover_estimator import ProverEstimatorEngine

        result = require_phase_result(ctx)
        proposals = ctx.proposals
        agents = ctx.agents

        if len(agents) < 2:
            logger.warning(
                "Prover-Estimator requires at least 2 agents, got %s. Falling back to majority.",
                len(agents),
            )
            await self._handle_majority_consensus(ctx)
            return

        prover = agents[0]
        estimator = agents[1] if len(agents) > 1 else agents[0]

        max_rounds = getattr(self.protocol, "prover_estimator_max_rounds", 2)
        pe_context = getattr(self.protocol, "prover_estimator_context", "")

        claim = ctx.env.task if ctx.env else ""
        if proposals:
            best_proposal = next(iter(proposals.values()))
            claim = f"{claim}\n\nProposal:\n{best_proposal}"

        engine = ProverEstimatorEngine(
            prover=prover,
            estimator=estimator,
            max_challenge_rounds=max_rounds,
            context=pe_context,
        )

        logger.info(
            "prover_estimator_start prover=%s estimator=%s rounds=%s",
            getattr(prover, "name", "unknown"),
            getattr(estimator, "name", "unknown"),
            max_rounds,
        )

        if self._notify_spectator:
            self._notify_spectator(
                "prover_estimator",
                details=f"Running Prover-Estimator with {len(agents)} agents",
            )

        try:
            pe_result = await engine.run(claim)

            result.confidence = pe_result.overall_confidence
            result.consensus_reached = pe_result.overall_confidence >= 0.5

            if proposals:
                result.final_answer = next(iter(proposals.values()))
            result.consensus_strength = (
                "strong"
                if pe_result.overall_confidence >= 0.8
                else "medium"
                if pe_result.overall_confidence >= 0.5
                else "weak"
            )

            if result.formal_verification is None:
                result.formal_verification = {}
            result.formal_verification["prover_estimator"] = {
                "overall_confidence": pe_result.overall_confidence,
                "grounding_score": pe_result.grounding_score,
                "obfuscation_detected": pe_result.obfuscation_detected,
                "subclaim_count": len(pe_result.subclaims),
                "challenge_count": len(pe_result.challenges),
            }

            logger.info(
                "prover_estimator_complete confidence=%.3f grounding=%.3f obfuscation=%s subclaims=%s",
                pe_result.overall_confidence,
                pe_result.grounding_score,
                pe_result.obfuscation_detected,
                len(pe_result.subclaims),
            )

            if self._notify_spectator:
                self._notify_spectator(
                    "consensus",
                    details=f"Prover-Estimator: confidence={pe_result.overall_confidence:.0%}, grounding={pe_result.grounding_score:.0%}",
                    metric=pe_result.overall_confidence,
                )

        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.error("prover_estimator_error: %s", e, exc_info=True)
            await self._handle_majority_consensus(ctx)

    async def _handle_crux_finder_consensus(self, ctx: "DebateContext") -> None:
        """Handle `crux_finder` consensus mode.

        Extracts load-bearing disagreements from the populated belief network
        and stores a ConsensusProof whose ``final_claim`` is the
        ``__CRUX_MAP__`` sentinel so downstream consumers can detect
        "no verdict by design" and route to the crux surface. On missing
        belief network — an explicit design choice to fail closed — we fall
        back to majority consensus to preserve the debate's protocol
        compatibility.

        The mode is guarded by ``ARAGORA_CRUX_FINDER_ENABLED`` (default off).
        A caller that explicitly requests this mode while it is disabled gets
        a typed error instead of an unrelated consensus verdict. Satisfies the
        DIC-15 (#6025) flag-gate requirement.
        """
        from aragora.debate.crux_mode import (
            build_crux_finder_result,
            require_crux_finder_enabled,
        )

        require_crux_finder_enabled()
        result = require_phase_result(ctx)

        from aragora.debate.consensus import build_proof_from_crux_finder

        belief_network = getattr(ctx, "belief_network", None)

        if belief_network is None:
            logger.warning("crux_finder_skipped reason=no_belief_network falling_back=majority")
            if not isinstance(getattr(result, "metadata", None), dict):
                result.metadata = {}
            result.metadata["crux_finder_skipped_reason"] = "no_belief_network"
            result.metadata["crux_finder_fallback_consensus"] = "majority"
            await self._handle_majority_consensus(ctx)
            return

        question = ctx.env.task if ctx.env else ""
        agent_names = [getattr(a, "name", "unknown") for a in ctx.agents]
        raw_claims = self._seed_crux_finder_current_claims(ctx, belief_network, question)

        try:
            crux_result = build_crux_finder_result(
                belief_network=belief_network,
                protocol=self.protocol,
                debate_id=ctx.debate_id or result.debate_id or "",
                question=question,
                agents=agent_names,
                rounds=getattr(result, "rounds_used", 0) or self.protocol.rounds,
                raw_claims=raw_claims,
                extra_metadata={
                    "current_debate_claim_count": len(raw_claims),
                    "belief_network_claim_count": len(getattr(belief_network, "nodes", {}) or {}),
                },
            )
            proof = build_proof_from_crux_finder(crux_result)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.error("crux_finder_error: %s", exc, exc_info=True)
            if not isinstance(getattr(result, "metadata", None), dict):
                result.metadata = {}
            result.metadata["crux_finder_skipped_reason"] = "crux_finder_error"
            result.metadata["crux_finder_error"] = str(exc)
            result.metadata["crux_finder_fallback_consensus"] = "majority"
            await self._handle_majority_consensus(ctx)
            return

        setattr(result, "consensus_proof", proof)
        result.consensus_reached = False
        result.final_answer = proof.final_claim
        result.consensus_strength = "weak"

        if result.formal_verification is None:
            result.formal_verification = {}
        result.formal_verification["crux_finder"] = {
            "crux_count": len(crux_result.analysis.cruxes),
            "convergence_barrier": round(crux_result.analysis.convergence_barrier, 4),
            "recommended_focus": list(crux_result.analysis.recommended_focus),
            "counterfactual_validation_enabled": bool(
                self.protocol.crux_finder_counterfactual_validation
            ),
        }

        logger.info(
            "crux_finder_complete cruxes=%s convergence_barrier=%.3f",
            len(crux_result.analysis.cruxes),
            crux_result.analysis.convergence_barrier,
        )

        if self._notify_spectator:
            self._notify_spectator(
                "consensus",
                details=(
                    f"Crux-finder: {len(crux_result.analysis.cruxes)} cruxes, "
                    f"barrier={crux_result.analysis.convergence_barrier:.2f}"
                ),
                metric=float(crux_result.analysis.convergence_barrier),
            )

    def _seed_crux_finder_current_claims(
        self,
        ctx: "DebateContext",
        belief_network: Any,
        question: str,
    ) -> list[dict[str, Any]]:
        """Add current-debate claims to the crux-finder belief network.

        KM seeding can leave the network empty for a live debate. Crux-finder
        must still analyze the debate that just happened instead of signing an
        empty crux map, so we project the current message/proposal stream into
        a small question-rooted belief graph.
        """
        if not hasattr(belief_network, "add_claim"):
            return []

        from aragora.reasoning.claims import RelationType, fast_extract_claims

        raw_claims: list[dict[str, Any]] = []
        claim_to_node = getattr(belief_network, "claim_to_node", {}) or {}
        root_claim_id = "current-debate-task"

        if question and root_claim_id not in claim_to_node:
            belief_network.add_claim(
                claim_id=root_claim_id,
                statement=question[:500],
                author="debate-task",
                initial_confidence=0.5,
            )

        seeded_claims: list[tuple[str, str, RelationType]] = []
        for source in self._iter_crux_finder_claim_sources(ctx):
            content = source["content"]
            extracted_claims = fast_extract_claims(content, source["agent"])
            if not extracted_claims:
                extracted_claims = [
                    {
                        "text": content[:500],
                        "author": source["agent"],
                        "confidence": 0.5,
                        "type": "assertion",
                    }
                ]

            for extracted in extracted_claims[:3]:
                if len(raw_claims) >= 20:
                    break

                statement = str(extracted.get("text") or "").strip()
                if not statement:
                    continue

                claim_id = f"current-debate-c{len(raw_claims) + 1:04d}"
                if claim_id in claim_to_node:
                    continue

                confidence = self._clamp_crux_claim_confidence(extracted.get("confidence", 0.5))
                relation = self._infer_crux_claim_relation(source["role"], statement)

                belief_network.add_claim(
                    claim_id=claim_id,
                    statement=statement[:500],
                    author=source["agent"],
                    initial_confidence=confidence,
                )

                if question and hasattr(belief_network, "add_factor"):
                    belief_network.add_factor(claim_id, root_claim_id, relation)
                    for previous_claim_id, previous_agent, previous_relation in seeded_claims:
                        if previous_agent != source["agent"] and previous_relation != relation:
                            belief_network.add_factor(
                                claim_id,
                                previous_claim_id,
                                RelationType.CONTRADICTS,
                            )

                seeded_claims.append((claim_id, source["agent"], relation))
                raw_claims.append(
                    {
                        "claim_id": claim_id,
                        "statement": statement[:500],
                        "author": source["agent"],
                        "role": source["role"],
                        "relation_to_question": relation.value,
                    }
                )

        return raw_claims

    def _iter_crux_finder_claim_sources(self, ctx: "DebateContext") -> list[dict[str, str]]:
        """Collect unique current-debate text sources for crux analysis."""
        sources: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add_source(agent: Any, role: Any, content: Any) -> None:
            normalized_content = str(content or "").strip()
            if len(normalized_content) < 10:
                return
            normalized_role = str(role or "proposer")
            if normalized_role not in {"proposer", "critic", "assistant", "synthesizer"}:
                return
            normalized_agent = str(agent or "unknown")
            key = (normalized_agent, normalized_content)
            if key in seen:
                return
            seen.add(key)
            sources.append(
                {
                    "agent": normalized_agent,
                    "role": normalized_role,
                    "content": normalized_content,
                }
            )

        result = getattr(ctx, "result", None)
        for message in list(getattr(result, "messages", []) or []):
            add_source(
                getattr(message, "agent", "unknown"),
                getattr(message, "role", "proposer"),
                getattr(message, "content", ""),
            )

        for message in list(getattr(ctx, "context_messages", []) or []):
            add_source(
                getattr(message, "agent", "unknown"),
                getattr(message, "role", "proposer"),
                getattr(message, "content", ""),
            )

        proposals = getattr(ctx, "proposals", {}) or {}
        for agent, proposal in proposals.items():
            add_source(agent, "proposer", proposal)

        return sources[:20]

    @staticmethod
    def _infer_crux_claim_relation(role: str, statement: str) -> Any:
        from aragora.reasoning.claims import RelationType

        lower = statement.lower()
        negative_markers = (
            " reject ",
            " oppose ",
            " against ",
            " should not ",
            " shouldn't ",
            " not approve ",
            " disagree ",
            " concern ",
            " risk ",
            " however ",
            " but ",
        )
        padded = f" {lower} "
        if role == "critic" or any(marker in padded for marker in negative_markers):
            return RelationType.CONTRADICTS
        return RelationType.SUPPORTS

    @staticmethod
    def _clamp_crux_claim_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.05, min(0.95, confidence))

    async def _collect_votes(self, ctx: "DebateContext") -> list["Vote"]:
        """Collect votes from all agents with outer timeout protection."""
        return await self._vote_collector.collect_votes(ctx)

    async def _collect_votes_with_errors(self, ctx: "DebateContext") -> tuple[list["Vote"], int]:
        """Collect votes with error tracking and outer timeout protection."""
        return await self._vote_collector.collect_votes_with_errors(ctx)

    def _compute_vote_groups(
        self,
        votes: list["Vote"],
        *,
        group_similar_votes: Callable | None | object = ...,
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        """Group similar votes and create choice mapping."""
        return self._vote_collector.compute_vote_groups(
            votes,
            group_similar_votes=group_similar_votes,
        )

    def _rlm_tally_inputs_are_fixed(
        self,
        *,
        protocol: Any | None = None,
        user_vote_contributions: tuple[_UserVoteContribution, ...] | None = None,
        group_similar_votes: Callable | None | object = ...,
        position_shuffling_enabled: bool | None = None,
    ) -> bool:
        """Return whether collection-time weights can safely authorize a final decision."""
        decision_protocol = self.protocol if protocol is None else protocol
        contributions = (
            self.user_votes if user_vote_contributions is None else user_vote_contributions
        )
        grouping = self._group_similar_votes if group_similar_votes is ... else group_similar_votes
        position_shuffling = (
            getattr(decision_protocol, "enable_position_shuffling", False)
            if position_shuffling_enabled is None
            else position_shuffling_enabled
        )
        vote_dependent_features = (
            "enable_self_vote_mitigation",
            "enable_verbosity_normalization",
            "verify_claims_during_consensus",
            "enable_evidence_weighting",
            "enable_process_evaluation",
            "enable_epistemic_hygiene",
            "enable_truth_ratio_weighting",
        )
        return not (
            contributions
            or grouping
            or position_shuffling
            or any(
                getattr(decision_protocol, feature, False) for feature in vote_dependent_features
            )
        )

    def _compute_vote_weights(
        self,
        ctx: "DebateContext",
        votes: list["Vote"] | None = None,
        *,
        agents: tuple[Any, ...] | None = None,
        protocol: Any | None = None,
        proposals: dict[str, str] | None = None,
        domain: str | None = None,
    ) -> dict[str, float]:
        """Pre-compute vote weights for all agents.

        Args:
            ctx: Debate context with agents and proposals
            votes: Optional list of votes for bias mitigation

        Returns:
            Dict mapping agent names to their weights
        """
        from aragora.debate.phases.weight_calculator import WeightCalculatorConfig

        decision_protocol = self.protocol if protocol is None else protocol

        # Get bias mitigation config from the decision snapshot.
        enable_self_vote = getattr(decision_protocol, "enable_self_vote_mitigation", False)
        enable_verbosity = getattr(decision_protocol, "enable_verbosity_normalization", False)

        config = WeightCalculatorConfig(
            # Agent-as-a-Judge bias mitigation
            enable_self_vote_mitigation=enable_self_vote,
            self_vote_mode=getattr(decision_protocol, "self_vote_mode", "downweight"),
            self_vote_downweight=getattr(decision_protocol, "self_vote_downweight", 0.5),
            enable_verbosity_normalization=enable_verbosity,
            verbosity_target_length=getattr(decision_protocol, "verbosity_target_length", 1000),
            verbosity_penalty_threshold=getattr(
                decision_protocol, "verbosity_penalty_threshold", 3.0
            ),
            verbosity_max_penalty=getattr(decision_protocol, "verbosity_max_penalty", 0.3),
        )

        # Get domain from context for domain-specific ELO weighting
        decision_domain = domain or getattr(ctx, "domain", None) or "general"

        calculator = WeightCalculator(
            memory=self.memory,
            elo_system=self.elo_system,
            flip_detector=self.flip_detector,
            agent_weights=self.agent_weights,
            calibration_tracker=self.calibration_tracker,
            get_calibration_weight=self._get_calibration_weight,
            config=config,
            domain=decision_domain,
        )

        eligible_agents = list(ctx.agents if agents is None else agents)

        # Use bias-aware computation if votes and proposals available
        decision_proposals = ctx.proposals if proposals is None else proposals
        if votes and decision_proposals and (enable_self_vote or enable_verbosity):
            return calculator.compute_weights_with_context(
                eligible_agents,
                votes,
                decision_proposals,
            )

        return calculator.compute_weights(eligible_agents)

    def _required_participation(self, total_agents: int) -> int:
        """Compute minimum required votes to proceed with consensus."""
        min_ratio = getattr(self.protocol, "min_participation_ratio", 0.5)
        min_count = getattr(self.protocol, "min_participation_count", 1)
        required = max(min_count, math.ceil(total_agents * min_ratio))
        # Never require more votes than agents available
        return min(required, max(total_agents, 1))

    def _ensure_quorum(
        self,
        ctx: "DebateContext",
        vote_count: int,
        *,
        required: int | None = None,
        total_agents: int | None = None,
    ) -> bool:
        """Ensure enough agents participated to make consensus meaningful."""
        total_agents = len(ctx.agents) if total_agents is None else total_agents
        required = self._required_participation(total_agents) if required is None else required
        if vote_count >= required:
            return True

        result = require_phase_result(ctx)
        result.final_answer = list(ctx.proposals.values())[0] if ctx.proposals else ""
        result.consensus_reached = False
        result.confidence = 0.0
        result.status = "insufficient_participation"

        logger.warning(
            "consensus_insufficient_participation votes=%d required=%d total_agents=%d",
            vote_count,
            required,
            total_agents,
            extra={
                "triage_diag_code": "insufficient_participation",
                "triage_diag_severity": "blocking",
            },
        )

        if self._notify_spectator:
            self._notify_spectator(
                "consensus",
                details=f"Insufficient participation ({vote_count}/{total_agents} votes)",
                metric=0.0,
            )

        return False

    def _record_vote_participation(
        self,
        ctx: "DebateContext",
        collection: MajorityVoteCollection,
        snapshot: _MajoritySnapshot,
    ) -> None:
        """Publish exact per-slot majority outcomes as additive result metadata."""
        result = require_phase_result(ctx)
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        metadata["vote_participation"] = {
            "eligible": snapshot.eligible_count,
            "received": len(collection.ballots),
            "failed": len(collection.failed_slots),
            "skipped": len(collection.skipped_slots),
        }
        result.metadata = metadata

    def _apply_calibration_to_votes(
        self,
        votes: list["Vote"],
        ctx: "DebateContext",
        *,
        calibration_summaries: dict[str, Any] | None = None,
    ) -> list["Vote"]:
        """Apply calibration adjustments to vote confidences."""
        if calibration_summaries is None and not self.calibration_tracker:
            return votes

        from aragora.agents.calibration import adjust_agent_confidence

        adjusted_votes: list[Any] = []
        for vote in votes:
            if isinstance(vote, Exception):
                adjusted_votes.append(vote)
                continue

            try:
                if calibration_summaries is None:
                    summary = self.calibration_tracker.get_calibration_summary(vote.agent)
                else:
                    summary = calibration_summaries.get(vote.agent)
                    if summary is None:
                        adjusted_votes.append(vote)
                        continue
                original_conf = vote.confidence
                adjusted_conf = adjust_agent_confidence(original_conf, summary)

                if adjusted_conf != original_conf:
                    from aragora.core import Vote

                    adjusted_vote = Vote(
                        agent=vote.agent,
                        choice=vote.choice,
                        reasoning=vote.reasoning,
                        confidence=adjusted_conf,
                        continue_debate=vote.continue_debate,
                    )
                    adjusted_votes.append(adjusted_vote)
                    logger.debug(
                        "calibration_confidence_adjustment agent=%s "
                        "original=%.2f adjusted=%.2f bias=%s",
                        vote.agent,
                        original_conf,
                        adjusted_conf,
                        summary.bias_direction,
                    )
                else:
                    adjusted_votes.append(vote)
            except (ValueError, KeyError, TypeError, AttributeError) as e:  # noqa: BLE001 - phase isolation
                logger.debug("Calibration adjustment failed for %s: %s", vote.agent, e)
                adjusted_votes.append(vote)

        return adjusted_votes

    def _capture_calibration_summaries(
        self,
        slots: tuple[VoterSlot, ...],
    ) -> tuple[tuple[str, Any], ...]:
        """Copy calibration inputs before any voter callback can mutate them."""
        if not self.calibration_tracker:
            return ()
        summaries: dict[str, Any] = {}
        for slot in slots:
            if slot.name in summaries:
                continue
            try:
                summaries[slot.name] = copy.deepcopy(
                    self.calibration_tracker.get_calibration_summary(slot.name)
                )
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                logger.debug(
                    "Calibration snapshot failed for %s: %s",
                    slot.name,
                    error,
                )
        return tuple(summaries.items())

    def _count_weighted_votes(
        self,
        votes: list["Vote"],
        choice_mapping: dict[str, str],
        vote_weight_cache: dict[str, float],
    ) -> tuple[dict[str, float], float]:
        """Count weighted votes."""
        vote_counts: dict[str, float] = {}
        total_weighted = 0.0

        for v in votes:
            if not isinstance(v, Exception):
                canonical = choice_mapping.get(v.choice, v.choice)
                weight = vote_weight_cache.get(v.agent, 1.0)
                vote_counts[canonical] = vote_counts.get(canonical, 0.0) + weight
                total_weighted += weight

        return vote_counts, total_weighted

    def _count_snapshot_votes(
        self,
        ballots: tuple[SlotVote, ...],
        choice_mapping: dict[str, str],
        slot_weights: tuple[float, ...],
    ) -> tuple[dict[str, float], float]:
        """Count received ballots while retaining every eligible slot in the denominator."""
        vote_counts: dict[str, float] = {}
        for ballot in ballots:
            canonical = choice_mapping.get(ballot.vote.choice, ballot.vote.choice)
            weight = slot_weights[ballot.slot.index]
            vote_counts[canonical] = vote_counts.get(canonical, 0.0) + weight
        return vote_counts, sum(slot_weights)

    def _add_user_votes(
        self,
        vote_counts: dict[str, float],
        total_weighted: float,
        choice_mapping: dict[str, str],
    ) -> tuple[dict[str, float], float]:
        """Add user votes to counts."""
        if self._drain_user_events:
            self._drain_user_events()

        base_user_weight = getattr(self.protocol, "user_vote_weight", 0.5)

        for user_vote in self.user_votes:
            choice = user_vote.get("choice", "")
            if choice:
                canonical = choice_mapping.get(choice, choice)
                intensity = user_vote.get("intensity", 5)

                if self._user_vote_multiplier:
                    intensity_multiplier = self._user_vote_multiplier(intensity, self.protocol)
                else:
                    intensity_multiplier = 1.0

                final_weight = base_user_weight * intensity_multiplier
                vote_counts[canonical] = vote_counts.get(canonical, 0.0) + final_weight
                total_weighted += final_weight

                logger.debug(
                    "user_vote user=%s choice=%s intensity=%s weight=%s",
                    user_vote.get("user_id", "anonymous"),
                    choice,
                    intensity,
                    final_weight,
                )

        return vote_counts, total_weighted

    def _capture_user_vote_contributions(
        self,
        protocol: Any,
    ) -> tuple[_UserVoteContribution, ...]:
        """Resolve user-vote weights at the immutable decision boundary."""
        base_user_weight = float(getattr(protocol, "user_vote_weight", 0.5))
        contributions: list[_UserVoteContribution] = []
        for user_vote in tuple(copy.deepcopy(self.user_votes)):
            choice = user_vote.get("choice", "")
            if not choice:
                continue
            intensity = user_vote.get("intensity", 5)
            multiplier = (
                self._user_vote_multiplier(intensity, copy.deepcopy(protocol))
                if self._user_vote_multiplier
                else 1.0
            )
            contributions.append(
                _UserVoteContribution(
                    choice=str(choice),
                    intensity=copy.deepcopy(intensity),
                    user_id=str(user_vote.get("user_id", "anonymous")),
                    weight=base_user_weight * float(multiplier),
                )
            )
        return tuple(contributions)

    @staticmethod
    def _add_snapshot_user_votes(
        vote_counts: dict[str, float],
        total_weighted: float,
        choice_mapping: dict[str, str],
        contributions: tuple[_UserVoteContribution, ...],
    ) -> tuple[dict[str, float], float]:
        """Add only the user-vote contributions captured by the snapshot."""
        for contribution in contributions:
            canonical = choice_mapping.get(contribution.choice, contribution.choice)
            vote_counts[canonical] = vote_counts.get(canonical, 0.0) + contribution.weight
            total_weighted += contribution.weight
            logger.debug(
                "user_vote user=%s choice=%s intensity=%s weight=%s",
                contribution.user_id,
                contribution.choice,
                contribution.intensity,
                contribution.weight,
            )
        return vote_counts, total_weighted

    def _normalize_choice_to_agent(
        self,
        choice: str,
        agents: list,
        proposals: dict[str, str],
    ) -> str:
        """Normalize a vote choice to an agent name."""
        return self._normalize_choice_to_names(
            choice,
            tuple(agent.name for agent in agents),
            proposals,
        )

    def _normalize_choice_to_names(
        self,
        choice: str,
        agent_names: tuple[str, ...],
        proposals: dict[str, str],
    ) -> str:
        """Normalize a choice against copied names rather than mutable agents."""
        if not choice:
            return choice

        choice_lower = choice.lower().strip()

        if choice in proposals:
            return choice

        for agent_name in proposals:
            if agent_name.lower() == choice_lower:
                return agent_name

        for agent_name in agent_names:
            agent_lower = agent_name.lower()

            if agent_lower == choice_lower:
                return agent_name

            if agent_lower.startswith(choice_lower):
                return agent_name

            if choice_lower.startswith(agent_lower):
                return agent_name

            if "-" in agent_name:
                base_name = agent_name.split("-")[0].lower()
                if base_name == choice_lower or choice_lower.startswith(base_name):
                    return agent_name

        logger.debug("vote_choice_no_match choice=%s agents=%s", choice, agent_names)
        return choice

    async def _verify_consensus_formally(self, ctx: "DebateContext") -> None:
        """Attempt formal verification of consensus claims using Lean4/Z3."""
        if not self.protocol:
            return

        formal_enabled = getattr(self.protocol, "formal_verification_enabled", False) or getattr(
            self.protocol, "enable_formal_verification", False
        )
        if not formal_enabled:
            return

        result = require_phase_result(ctx)
        if not result.final_answer:
            return

        timeout = getattr(self.protocol, "formal_verification_timeout", 30.0)
        languages = getattr(self.protocol, "formal_verification_languages", ["z3_smt"])

        logger.info("formal_verification_start languages=%s timeout=%s", languages, timeout)

        try:
            from aragora.verification.formal import get_formal_verification_manager

            manager = get_formal_verification_manager()

            status = manager.status_report()
            if not status.get("any_available", False):
                logger.debug("formal_verification_skip no backends available")
                result.formal_verification = {
                    "status": "skipped",
                    "reason": "No formal verification backends available",
                    "backends_checked": languages,
                }
                return

            if getattr(self.protocol, "enable_hilbert_proofing", False):
                from aragora.verification.hilbert import HilbertProver

                prover = HilbertProver(
                    manager=manager,
                    max_depth=getattr(self.protocol, "hilbert_max_depth", 2),
                    min_subclaims=getattr(self.protocol, "hilbert_min_subclaims", 2),
                    timeout_seconds=timeout,
                )
                proof_tree = await asyncio.wait_for(
                    prover.prove(
                        claim=result.final_answer,
                        claim_type="DEBATE_CONSENSUS",
                        context=ctx.env.task if ctx.env else "",
                    ),
                    timeout=timeout + 5.0,
                )
                result.formal_verification = proof_tree.to_dict()
                verification_result = proof_tree.result
                verification_status = proof_tree.status
                verification_is_verified = proof_tree.is_verified
                verification_language = (
                    verification_result.language.value
                    if verification_result and verification_result.language
                    else None
                )
            else:
                direct_verification_result = await asyncio.wait_for(
                    manager.attempt_formal_verification(
                        claim=result.final_answer,
                        claim_type="DEBATE_CONSENSUS",
                        context=ctx.env.task if ctx.env else "",
                        timeout_seconds=timeout,
                    ),
                    timeout=timeout + 5.0,
                )

                result.formal_verification = direct_verification_result.to_dict()
                verification_status = direct_verification_result.status.value
                verification_is_verified = direct_verification_result.is_verified
                verification_language = (
                    direct_verification_result.language.value
                    if direct_verification_result.language
                    else None
                )
                verification_result = direct_verification_result

            logger.info(
                "formal_verification_complete status=%s language=%s verified=%s",
                verification_status,
                verification_language or "none",
                verification_is_verified,
            )

            if ctx.event_emitter:
                try:
                    from aragora.events.types import StreamEvent, StreamEventType

                    ctx.event_emitter.emit(
                        StreamEvent(
                            type=StreamEventType.FORMAL_VERIFICATION_RESULT,
                            loop_id=ctx.loop_id,
                            data={
                                "debate_id": ctx.debate_id,
                                "status": verification_status,
                                "is_verified": verification_is_verified,
                                "language": verification_language,
                                "formal_statement": (
                                    verification_result.formal_statement[:500]
                                    if verification_result and verification_result.formal_statement
                                    else None
                                ),
                            },
                        )
                    )
                except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
                    logger.debug("formal_verification_event_error: %s", e)

        except asyncio.TimeoutError:
            logger.warning("formal_verification_timeout timeout=%ss", timeout)
            result.formal_verification = {
                "status": "timeout",
                "timeout_seconds": timeout,
                "is_verified": False,
            }
        except ImportError as e:
            logger.debug("formal_verification_import_error: %s", e)
            result.formal_verification = {
                "status": "unavailable",
                "reason": "Formal verification module not available",
                "is_verified": False,
            }
        except (RuntimeError, OSError, ConnectionError) as e:  # noqa: BLE001 - phase isolation
            logger.warning("formal_verification_error: %s", e)
            result.formal_verification = {
                "status": "error",
                "error": f"verification_error:{type(e).__name__}",
                "is_verified": False,
            }
