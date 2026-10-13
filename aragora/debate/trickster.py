"""
Evidence-Powered Trickster - Hollow Consensus Detection & Challenge System.

This module implements the "trickster" pattern for maintaining intellectual rigor
in multi-agent debates. It detects when agents are reaching consensus without
substantive evidence backing, and injects targeted challenges to restore rigor.

The system operates in three phases:
1. Monitor - Continuously assess evidence quality during debate rounds
2. Detect - Identify hollow consensus (high convergence, low evidence quality)
3. Intervene - Inject targeted challenges based on specific quality gaps

Integration patterns:
- Works alongside wisdom_injector.py (similar intervention architecture)
- Uses convergence.py for semantic similarity detection
- Leverages roles.py QUALITY_CHALLENGER role for interventions
- Can trigger breakpoints.py HOLLOW_CONSENSUS events

Based on the Aragora nomic loop debate proposal for "Evidence-Powered Trickster"
that identified evidence quality and intervention timing as dual aspects of
maintaining intellectual rigor in AI debates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.debate.cross_proposal_analyzer import (
    CrossProposalAnalysis,
    CrossProposalAnalyzer,
)
from aragora.debate.evidence_quality import (
    EvidenceQualityAnalyzer,
    EvidenceQualityScore,
    HollowConsensusAlert,
    HollowConsensusDetector,
)
from aragora.debate.roles import ROLE_PROMPTS, CognitiveRole, RoleAssignment

logger = logging.getLogger(__name__)


def _get_evidence_linker_class():
    """Lazy import of EvidenceClaimLinker to avoid scipy/numpy import failures.

    Returns:
        EvidenceClaimLinker class if available, None otherwise
    """
    try:
        from aragora.debate.evidence_linker import EvidenceClaimLinker

        return EvidenceClaimLinker
    except ImportError as e:
        logger.debug("EvidenceClaimLinker not available: %s", e)
        return None


class InterventionType(Enum):
    """Types of trickster interventions."""

    CHALLENGE_PROMPT = "challenge_prompt"  # Inject challenge into next round
    QUALITY_ROLE = "quality_role"  # Assign QUALITY_CHALLENGER role
    EXTENDED_ROUND = "extended_round"  # Add extra round for evidence
    BREAKPOINT = "breakpoint"  # Trigger human review breakpoint
    NOVELTY_CHALLENGE = "novelty_challenge"  # Challenge agents to seek fresh perspectives
    EVIDENCE_GAP = "evidence_gap"  # Challenge agents on unsupported claims
    ECHO_CHAMBER = "echo_chamber"  # Challenge agents to seek independent sources


@dataclass
class TricksterIntervention:
    """A trickster intervention to restore debate rigor."""

    intervention_type: InterventionType
    round_num: int
    target_agents: list[str]
    challenge_text: str
    evidence_gaps: dict[str, list[str]]  # agent -> list of gaps
    priority: float  # 0-1, higher = more urgent
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TricksterConfig:
    """Configuration for the trickster system."""

    # Sensitivity (convenience parameter - higher = more sensitive detection)
    # Maps to hollow_detection_threshold: sensitivity 0.7 -> threshold 0.3
    sensitivity: float = 0.5

    # Thresholds - tuned for earlier detection of hollow consensus
    min_quality_threshold: float = 0.65  # Minimum acceptable evidence quality (raised from 0.4)
    hollow_detection_threshold: float = 0.5  # Alert severity to trigger (raised from 0.3)
    intervention_cooldown_rounds: int = 1  # Rounds between interventions (reduced from 2)

    # Features
    enable_challenge_prompts: bool = True
    enable_role_assignment: bool = True
    enable_extended_rounds: bool = True  # Allow adding rounds when needed (was False)
    enable_breakpoints: bool = True

    # Limits
    max_challenges_per_round: int = 3
    max_interventions_total: int = 5

    def __post_init__(self):
        """Adjust thresholds based on sensitivity if sensitivity was explicitly set."""
        # Higher sensitivity = lower threshold (more sensitive to hollow consensus)
        # sensitivity 0.0 -> threshold 0.8 (very insensitive)
        # sensitivity 0.5 -> threshold 0.5 (balanced)
        # sensitivity 1.0 -> threshold 0.2 (very sensitive)
        if self.sensitivity != 0.5:  # Only adjust if sensitivity was changed from default
            # Round to stabilize exact-value expectations in config tests.
            self.hollow_detection_threshold = round(0.8 - (self.sensitivity * 0.6), 10)


@dataclass
class TricksterState:
    """Internal state tracking for the trickster."""

    interventions: list[TricksterIntervention] = field(default_factory=list)
    quality_history: list[dict[str, EvidenceQualityScore]] = field(default_factory=list)
    last_intervention_round: int = -10
    hollow_alerts: list[HollowConsensusAlert] = field(default_factory=list)
    total_interventions: int = 0


class EvidencePoweredTrickster:
    """
    The Evidence-Powered Trickster - maintains intellectual rigor in debates.

    This class monitors evidence quality during debates and intervenes when
    it detects hollow consensus forming. It operates passively until triggered,
    then injects targeted challenges based on specific evidence gaps.

    Usage:
        trickster = EvidencePoweredTrickster()

        # In debate round loop:
        intervention = trickster.check_and_intervene(
            responses={"agent1": "...", "agent2": "..."},
            convergence_similarity=0.85,
            round_num=2,
        )

        if intervention:
            # Apply intervention (inject prompt, assign role, etc.)
            apply_intervention(intervention)
    """

    def __init__(
        self,
        config: TricksterConfig | None = None,
        domain_configs: dict[str, TricksterConfig] | None = None,
        on_intervention: Callable[[TricksterIntervention], None] | None = None,
        on_alert: Callable[[HollowConsensusAlert], None] | None = None,
        linker: Any | None = None,
    ):
        """
        Initialize the trickster.

        Args:
            config: Default configuration options
            domain_configs: Domain-specific configuration overrides. Maps domain names
                (e.g., "medical", "legal", "financial") to TricksterConfig instances
                with domain-appropriate thresholds. Use resolve_config() to get the
                effective config for a specific domain.
            on_intervention: Callback when intervention is triggered
            on_alert: Callback when hollow consensus is detected
            linker: Evidence-claim linker for semantic evidence validation
        """
        self.config = config or TricksterConfig()
        self.domain_configs = domain_configs or {}
        self.on_intervention = on_intervention
        self.on_alert = on_alert

        self._state = TricksterState()
        self._analyzer = EvidenceQualityAnalyzer()
        self._detector = HollowConsensusDetector(
            min_quality_threshold=self.config.min_quality_threshold,
        )

        # Lazy load EvidenceClaimLinker to avoid scipy/numpy import failures
        self._linker = linker
        if self._linker is None:
            EvidenceClaimLinker = _get_evidence_linker_class()
            if EvidenceClaimLinker is not None:
                self._linker = EvidenceClaimLinker()

        # CrossProposalAnalyzer can work with None linker
        self._cross_analyzer = CrossProposalAnalyzer(self._linker)

    def resolve_config(self, domain: str | None = None) -> TricksterConfig:
        """Resolve the effective config for a given domain.

        Args:
            domain: Domain name (e.g., "medical", "legal", "financial").
                If None or not found in domain_configs, returns the default config.

        Returns:
            TricksterConfig for the specified domain, or the default config.

        Example:
            # Medical domain with stricter thresholds
            trickster = EvidencePoweredTrickster(
                config=TricksterConfig(),  # default
                domain_configs={
                    "medical": TricksterConfig(sensitivity=0.8),  # more sensitive
                    "legal": TricksterConfig(min_quality_threshold=0.7),
                },
            )
            config = trickster.resolve_config("medical")  # Returns medical config
            config = trickster.resolve_config("unknown")  # Returns default config
        """
        if domain and domain in self.domain_configs:
            return self.domain_configs[domain]
        return self.config

    def check_and_intervene(
        self,
        responses: dict[str, str],
        convergence_similarity: float,
        round_num: int,
    ) -> TricksterIntervention | None:
        """
        Check evidence quality and potentially intervene.

        This is the main entry point, called after each debate round.

        Args:
            responses: Agent name -> response text
            convergence_similarity: Semantic similarity from ConvergenceDetector
            round_num: Current round number

        Returns:
            TricksterIntervention if intervention needed, None otherwise
        """
        # Analyze evidence quality
        quality_scores = self._analyzer.analyze_batch(responses, round_num)
        self._state.quality_history.append(quality_scores)

        # Check for hollow consensus
        alert = self._detector.check(responses, convergence_similarity, round_num)
        self._state.hollow_alerts.append(alert)

        if self.on_alert and alert.detected:
            self.on_alert(alert)

        # NEW: Cross-proposal analysis for converging responses
        cross_analysis: CrossProposalAnalysis | None = None
        if convergence_similarity > 0.6:
            cross_analysis = self._cross_analyzer.analyze(responses)

            # Check for evidence gaps (claims without any supporting evidence)
            if cross_analysis.evidence_gaps:
                intervention = self._create_evidence_gap_intervention(cross_analysis, round_num)
                if intervention:
                    return self._record_intervention(intervention, round_num)

            # Check for echo chamber (agents citing same limited evidence)
            if cross_analysis.redundancy_score > 0.7:
                intervention = self._create_echo_chamber_intervention(cross_analysis, round_num)
                if intervention:
                    return self._record_intervention(intervention, round_num)

        # Decide on intervention based on traditional hollow consensus check
        if not alert.detected:
            logger.debug("trickster_pass round=%s reason=quality_acceptable", round_num)
            return None

        if alert.severity < self.config.hollow_detection_threshold:
            logger.debug(
                "trickster_pass round=%s reason=below_threshold severity=%.2f",
                round_num,
                alert.severity,
            )
            return None

        # Check cooldown
        rounds_since = round_num - self._state.last_intervention_round
        if rounds_since < self.config.intervention_cooldown_rounds:
            logger.debug("trickster_cooldown round=%s rounds_since=%s", round_num, rounds_since)
            return None

        # Check max interventions
        if self._state.total_interventions >= self.config.max_interventions_total:
            logger.debug(
                "trickster_limit round=%s total=%s", round_num, self._state.total_interventions
            )
            return None

        # Create intervention
        intervention = self._create_intervention(alert, quality_scores, round_num, cross_analysis)

        return self._record_intervention(intervention, round_num)

    def _record_intervention(
        self,
        intervention: TricksterIntervention,
        round_num: int,
    ) -> TricksterIntervention:
        """Record an intervention and update state."""
        # Check cooldown
        rounds_since = round_num - self._state.last_intervention_round
        if rounds_since < self.config.intervention_cooldown_rounds:
            logger.debug("trickster_cooldown round=%s", round_num)
            return intervention  # Still return for caller, but skip recording

        # Check max interventions
        if self._state.total_interventions >= self.config.max_interventions_total:
            logger.debug("trickster_limit round=%s", round_num)
            return intervention

        # Track state
        self._state.interventions.append(intervention)
        self._state.last_intervention_round = round_num
        self._state.total_interventions += 1

        logger.info(
            "trickster_intervene round=%s type=%s targets=%s",
            round_num,
            intervention.intervention_type.value,
            intervention.target_agents,
        )

        if self.on_intervention:
            self.on_intervention(intervention)

        return intervention

    def _create_evidence_gap_intervention(
        self,
        cross_analysis: CrossProposalAnalysis,
        round_num: int,
    ) -> TricksterIntervention | None:
        """Create intervention for evidence gaps."""
        if not cross_analysis.evidence_gaps:
            return None

        top_gap = cross_analysis.evidence_gaps[0]

        challenge_text = self._build_evidence_gap_challenge(cross_analysis)

        return TricksterIntervention(
            intervention_type=InterventionType.EVIDENCE_GAP,
            round_num=round_num,
            target_agents=top_gap.agents_making_claim,
            challenge_text=challenge_text,
            evidence_gaps={},
            priority=top_gap.gap_severity,
            metadata={
                "gap_claim": top_gap.claim[:200],
                "gap_severity": top_gap.gap_severity,
                "total_gaps": len(cross_analysis.evidence_gaps),
            },
        )

    def _build_evidence_gap_challenge(
        self,
        cross_analysis: CrossProposalAnalysis,
    ) -> str:
        """Build challenge text for evidence gaps."""
        lines = [
            "## EVIDENCE GAP DETECTED",
            "",
            "Multiple agents are making claims **without supporting evidence**.",
            "Before reaching consensus, please address these gaps:",
            "",
        ]

        for gap in cross_analysis.evidence_gaps[:3]:
            agents_str = ", ".join(gap.agents_making_claim)
            lines.append(f'- **Claim by {agents_str}**: "{gap.claim[:100]}..."')
            lines.append("  → No evidence provided by any agent")
            lines.append("")

        lines.extend(
            [
                "### Required Actions:",
                "1. Provide specific sources or data supporting these claims",
                "2. If no evidence exists, reconsider the claim",
                "3. Distinguish between speculation and supported conclusions",
                "",
                "*This challenge was triggered by cross-proposal evidence analysis.*",
            ]
        )

        return "\n".join(lines)

    def _create_echo_chamber_intervention(
        self,
        cross_analysis: CrossProposalAnalysis,
        round_num: int,
    ) -> TricksterIntervention | None:
        """Create intervention for echo chamber detection."""
        if cross_analysis.redundancy_score <= 0.7:
            return None

        challenge_text = self._build_echo_chamber_challenge(cross_analysis)

        return TricksterIntervention(
            intervention_type=InterventionType.ECHO_CHAMBER,
            round_num=round_num,
            target_agents=list(cross_analysis.agent_coverage.keys()),
            challenge_text=challenge_text,
            evidence_gaps={},
            priority=cross_analysis.redundancy_score,
            metadata={
                "redundancy_score": cross_analysis.redundancy_score,
                "unique_sources": cross_analysis.unique_evidence_sources,
                "total_sources": cross_analysis.total_evidence_sources,
            },
        )

    def _build_echo_chamber_challenge(
        self,
        cross_analysis: CrossProposalAnalysis,
    ) -> str:
        """Build challenge text for echo chamber."""
        lines = [
            "## ECHO CHAMBER WARNING",
            "",
            f"Agents are citing the **same limited evidence** "
            f"({cross_analysis.redundancy_score:.0%} redundancy).",
            "",
            f"- Unique evidence sources: {cross_analysis.unique_evidence_sources}",
            f"- Total citations: {cross_analysis.total_evidence_sources}",
            "",
            "This suggests agents may be reinforcing each other's views "
            "without independent validation.",
            "",
            "### Required Actions:",
            "1. Each agent should seek **independent** evidence sources",
            "2. Consider alternative interpretations of the shared evidence",
            "3. Challenge assumptions that are based on repeated assertions",
            "4. Look for evidence that might **contradict** the emerging consensus",
            "",
            "*This challenge was triggered by cross-proposal redundancy detection.*",
        ]

        return "\n".join(lines)

    def _create_intervention(
        self,
        alert: HollowConsensusAlert,
        quality_scores: dict[str, EvidenceQualityScore],
        round_num: int,
        cross_analysis: CrossProposalAnalysis | None = None,
    ) -> TricksterIntervention:
        """Create an appropriate intervention based on the alert."""
        # Identify lowest quality agents
        sorted_agents = sorted(
            alert.agent_scores.items(),
            key=lambda x: x[1],
        )
        target_agents = [
            agent for agent, score in sorted_agents if score < self.config.min_quality_threshold
        ][: self.config.max_challenges_per_round]

        if not target_agents:
            target_agents = [sorted_agents[0][0]] if sorted_agents else []

        # Identify evidence gaps per agent
        evidence_gaps: dict[str, list[str]] = {}
        for agent, score in quality_scores.items():
            gaps = []
            if score.citation_density < 0.2:
                gaps.append("citations")
            if score.specificity_score < 0.3:
                gaps.append("specificity")
            if score.logical_chain_score < 0.3:
                gaps.append("reasoning")
            if score.evidence_diversity < 0.2:
                gaps.append("evidence_diversity")
            if gaps:
                evidence_gaps[agent] = gaps

        # Build challenge text
        challenge_text = self._build_challenge(alert, evidence_gaps, target_agents)

        # Determine intervention type
        intervention_type = self._select_intervention_type(alert, round_num)

        # Build metadata including cross-analysis if available
        metadata: dict[str, Any] = {
            "avg_quality": alert.avg_quality,
            "min_quality": alert.min_quality,
            "quality_variance": alert.quality_variance,
            "reason": alert.reason,
        }

        if cross_analysis:
            metadata.update(
                {
                    "cross_analysis_redundancy": cross_analysis.redundancy_score,
                    "cross_analysis_corroboration": cross_analysis.evidence_corroboration_score,
                    "cross_analysis_gaps_count": len(cross_analysis.evidence_gaps),
                }
            )

        return TricksterIntervention(
            intervention_type=intervention_type,
            round_num=round_num,
            target_agents=target_agents,
            challenge_text=challenge_text,
            evidence_gaps=evidence_gaps,
            priority=alert.severity,
            metadata=metadata,
        )

    def _build_challenge(
        self,
        alert: HollowConsensusAlert,
        evidence_gaps: dict[str, list[str]],
        target_agents: list[str],
    ) -> str:
        """Build the challenge prompt text."""
        lines = [
            "## QUALITY CHALLENGE - Evidence Review Required",
            "",
            "The current discussion shows signs of **hollow consensus** - "
            "positions are converging without sufficient evidence backing.",
            "",
        ]

        # Use recommended challenges from detector
        if alert.recommended_challenges:
            lines.append("### Specific Challenges:")
            for challenge in alert.recommended_challenges:
                lines.append(f"- {challenge}")
            lines.append("")

        # Add agent-specific gaps
        if evidence_gaps:
            lines.append("### Evidence Gaps by Agent:")
            for agent, gaps in evidence_gaps.items():
                gaps_str = ", ".join(gaps)
                lines.append(f"- **{agent}**: Missing {gaps_str}")
            lines.append("")

        lines.extend(
            [
                "### Before Proceeding:",
                "1. Provide specific citations or data sources",
                "2. Replace vague language with concrete numbers",
                "3. Give real examples that demonstrate your points",
                "4. Explain the logical chain from premise to conclusion",
                "",
                "*This challenge was triggered by the Evidence-Powered Trickster system.*",
            ]
        )

        return "\n".join(lines)

    def _select_intervention_type(
        self,
        alert: HollowConsensusAlert,
        round_num: int,
    ) -> InterventionType:
        """Select the most appropriate intervention type."""
        # High severity -> breakpoint if enabled
        if alert.severity > 0.8 and self.config.enable_breakpoints:
            return InterventionType.BREAKPOINT

        # First intervention -> role assignment if enabled
        if self._state.total_interventions == 0 and self.config.enable_role_assignment:
            return InterventionType.QUALITY_ROLE

        # Default -> challenge prompt
        if self.config.enable_challenge_prompts:
            return InterventionType.CHALLENGE_PROMPT

        # Fallback
        return InterventionType.CHALLENGE_PROMPT

    def get_quality_challenger_assignment(
        self,
        agent_name: str,
        round_num: int,
    ) -> RoleAssignment:
        """
        Get a QUALITY_CHALLENGER role assignment for an agent.

        Use this when intervention_type is QUALITY_ROLE.
        """
        return RoleAssignment(
            agent_name=agent_name,
            role=CognitiveRole.QUALITY_CHALLENGER,
            round_num=round_num,
            role_prompt=ROLE_PROMPTS[CognitiveRole.QUALITY_CHALLENGER],
        )

    def create_novelty_challenge(
        self,
        low_novelty_agents: list[str],
        novelty_scores: dict[str, float],
        round_num: int,
    ) -> TricksterIntervention | None:
        """
        Create a novelty challenge intervention for agents with stale proposals.

        Called by DebateRoundsPhase when NoveltyTracker detects low novelty.

        Args:
            low_novelty_agents: Agents whose proposals are too similar to prior rounds
            novelty_scores: Per-agent novelty scores (0-1, higher = more novel)
            round_num: Current round number

        Returns:
            TricksterIntervention if challenge should be issued, None otherwise
        """
        if not low_novelty_agents:
            return None

        # Check cooldown
        rounds_since = round_num - self._state.last_intervention_round
        if rounds_since < self.config.intervention_cooldown_rounds:
            logger.debug(
                "novelty_challenge_cooldown round=%s rounds_since=%s", round_num, rounds_since
            )
            return None

        # Check max interventions
        if self._state.total_interventions >= self.config.max_interventions_total:
            logger.debug(
                "novelty_challenge_limit round=%s total=%s",
                round_num,
                self._state.total_interventions,
            )
            return None

        # Build challenge text for novelty
        challenge_text = self._build_novelty_challenge(low_novelty_agents, novelty_scores)

        # Calculate priority based on how low the novelty is
        min_novelty = min(novelty_scores.get(a, 1.0) for a in low_novelty_agents)
        priority = 1.0 - min_novelty  # Lower novelty = higher priority

        intervention = TricksterIntervention(
            intervention_type=InterventionType.NOVELTY_CHALLENGE,
            round_num=round_num,
            target_agents=low_novelty_agents,
            challenge_text=challenge_text,
            evidence_gaps={},  # Novelty challenges don't focus on evidence gaps
            priority=priority,
            metadata={
                "novelty_scores": novelty_scores,
                "min_novelty": min_novelty,
                "reason": "proposals_too_similar_to_prior_rounds",
            },
        )

        # Track state
        self._state.interventions.append(intervention)
        self._state.last_intervention_round = round_num
        self._state.total_interventions += 1

        logger.info(
            "novelty_challenge_created round=%s targets=%s min_novelty=%.2f",
            round_num,
            low_novelty_agents,
            min_novelty,
        )

        if self.on_intervention:
            self.on_intervention(intervention)

        return intervention

    def _build_novelty_challenge(
        self,
        low_novelty_agents: list[str],
        novelty_scores: dict[str, float],
    ) -> str:
        """Build the challenge prompt for novelty issues."""
        lines = [
            "## NOVELTY CHALLENGE - Seek Alternative Perspectives",
            "",
            "Your current proposals are **too similar** to ideas already discussed "
            "in previous rounds. The debate risks converging to mediocrity.",
            "",
            "### Agents Needing Fresh Perspectives:",
        ]

        for agent in low_novelty_agents:
            score = novelty_scores.get(agent, 0.0)
            lines.append(f"- **{agent}**: Novelty {score:.0%} (below threshold)")

        lines.extend(
            [
                "",
                "### To Increase Novelty:",
                "1. Consider angles you haven't explored yet",
                "2. Challenge assumptions from prior rounds",
                "3. Introduce new evidence or frameworks",
                "4. Play devil's advocate to your own position",
                "5. Think about edge cases or minority viewpoints",
                "",
                "**Goal**: Bring fresh ideas that meaningfully differ from what's "
                "already been said, while still addressing the core question.",
                "",
                "*This challenge was triggered by the Novelty Tracking system.*",
            ]
        )

        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        """Get trickster statistics for debugging/monitoring."""
        avg_quality_per_round = []
        for round_scores in self._state.quality_history:
            if round_scores:
                avg = sum(s.overall_quality for s in round_scores.values()) / len(round_scores)
                avg_quality_per_round.append(avg)

        return {
            "total_interventions": self._state.total_interventions,
            "hollow_alerts_detected": sum(1 for a in self._state.hollow_alerts if a.detected),
            "avg_quality_per_round": avg_quality_per_round,
            "interventions": [
                {
                    "round": i.round_num,
                    "type": i.intervention_type.value,
                    "targets": i.target_agents,
                    "priority": i.priority,
                }
                for i in self._state.interventions
            ],
        }

    def get_elo_adjustments(self) -> dict[str, float]:
        """Compute ELO adjustment recommendations based on trickster signals.

        Agents targeted by interventions receive negative adjustments
        (penalties for building hollow consensus, lacking evidence, or
        creating echo chambers). The penalty scales with frequency and
        severity of interventions.

        Returns:
            Dict of agent_name → ELO adjustment score (-1.0 to 0.0).
            Negative = penalty. Agents not targeted get no entry.
        """
        agent_penalties: dict[str, float] = {}
        intervention_type_weights = {
            InterventionType.EVIDENCE_GAP: -0.3,  # Missing evidence
            InterventionType.ECHO_CHAMBER: -0.2,  # Citing same sources
            InterventionType.CHALLENGE_PROMPT: -0.15,  # Hollow consensus
            InterventionType.QUALITY_ROLE: -0.1,  # Assigned quality role
            InterventionType.NOVELTY_CHALLENGE: -0.1,  # Stale proposals
            InterventionType.EXTENDED_ROUND: -0.05,  # Needed more time
            InterventionType.BREAKPOINT: -0.4,  # Human review needed
        }

        for intervention in self._state.interventions:
            weight = intervention_type_weights.get(intervention.intervention_type, -0.1)
            # Scale by priority (0-1)
            penalty = weight * intervention.priority
            for agent in intervention.target_agents:
                agent_penalties[agent] = agent_penalties.get(agent, 0.0) + penalty

        # Clamp penalties to [-1.0, 0.0]
        return {agent: max(penalty, -1.0) for agent, penalty in agent_penalties.items()}

    def get_evidence_quality_scores(self) -> dict[str, float]:
        """Get average evidence quality per agent across all rounds.

        Returns:
            Dict of agent_name → average evidence quality (0.0-1.0).
            Higher = better evidence quality. Can be used as ELO bonus.
        """
        agent_totals: dict[str, list[float]] = {}
        for round_scores in self._state.quality_history:
            for agent, score in round_scores.items():
                agent_totals.setdefault(agent, []).append(score.overall_quality)

        return {
            agent: sum(scores) / len(scores) for agent, scores in agent_totals.items() if scores
        }

    def reset(self) -> None:
        """Reset trickster state for a new debate."""
        self._state = TricksterState()


def create_trickster_for_debate(
    min_quality: float = 0.4,
    enable_breakpoints: bool = True,
) -> EvidencePoweredTrickster:
    """
    Factory function to create a trickster for a debate.

    Args:
        min_quality: Minimum acceptable evidence quality (0-1)
        enable_breakpoints: Whether to allow human review triggers

    Returns:
        Configured EvidencePoweredTrickster instance
    """
    config = TricksterConfig(
        min_quality_threshold=min_quality,
        enable_breakpoints=enable_breakpoints,
    )
    return EvidencePoweredTrickster(config=config)


__all__ = [
    "InterventionType",
    "TricksterIntervention",
    "TricksterConfig",
    "TricksterState",
    "EvidencePoweredTrickster",
    "create_trickster_for_debate",
]
