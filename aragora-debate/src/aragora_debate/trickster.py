"""Evidence-Powered Trickster — Hollow Consensus Detection & Challenge System.

This module implements the "trickster" pattern for maintaining intellectual rigor
in multi-agent debates.  It detects when agents are reaching consensus without
substantive evidence backing, and injects targeted challenges to restore rigor.

The system operates in three phases:

1. **Monitor** — Continuously assess evidence quality during debate rounds
2. **Detect** — Identify hollow consensus (high convergence, low evidence quality)
3. **Intervene** — Inject targeted challenges based on specific quality gaps

Example::

    from aragora_debate.trickster import EvidencePoweredTrickster, TricksterConfig

    trickster = EvidencePoweredTrickster(
        config=TricksterConfig(sensitivity=0.7),
    )

    intervention = trickster.check_and_intervene(
        responses={"agent1": "...", "agent2": "..."},
        convergence_similarity=0.85,
        round_num=2,
    )

    if intervention:
        print(intervention.challenge_text)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora_debate.cross_analysis import CrossProposalAnalysis, CrossProposalAnalyzer
from aragora_debate.evidence import (
    EvidenceQualityAnalyzer,
    EvidenceQualityScore,
    HollowConsensusAlert,
    HollowConsensusDetector,
)

logger = logging.getLogger(__name__)


class InterventionType(Enum):
    """Types of trickster interventions."""

    CHALLENGE_PROMPT = "challenge_prompt"  # Inject challenge into next round
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

    # Sensitivity (convenience parameter — higher = more sensitive detection)
    # Maps to hollow_detection_threshold: sensitivity 0.7 -> threshold 0.38
    sensitivity: float = 0.5

    # Thresholds
    min_quality_threshold: float = 0.65
    hollow_detection_threshold: float = 0.5
    intervention_cooldown_rounds: int = 1

    # Limits
    max_challenges_per_round: int = 3
    max_interventions_total: int = 5

    def __post_init__(self) -> None:
        """Adjust thresholds based on sensitivity."""
        # Higher sensitivity = lower threshold (more sensitive)
        # sensitivity 0.0 -> threshold 0.8
        # sensitivity 0.5 -> threshold 0.5
        # sensitivity 1.0 -> threshold 0.2
        if self.sensitivity != 0.5:
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
    """The Evidence-Powered Trickster — maintains intellectual rigor in debates.

    This class monitors evidence quality during debates and intervenes when
    it detects hollow consensus forming.  It operates passively until
    triggered, then injects targeted challenges based on specific evidence
    gaps.

    Args:
        config: Configuration options.
        domain_configs: Domain-specific configuration overrides.
        on_intervention: Callback when intervention is triggered.
        on_alert: Callback when hollow consensus is detected.

    Example::

        trickster = EvidencePoweredTrickster()

        # In debate round loop:
        intervention = trickster.check_and_intervene(
            responses={"agent1": "...", "agent2": "..."},
            convergence_similarity=0.85,
            round_num=2,
        )

        if intervention:
            apply_intervention(intervention)
    """

    def __init__(
        self,
        config: TricksterConfig | None = None,
        domain_configs: dict[str, TricksterConfig] | None = None,
        on_intervention: Callable[[TricksterIntervention], None] | None = None,
        on_alert: Callable[[HollowConsensusAlert], None] | None = None,
    ) -> None:
        self.config = config or TricksterConfig()
        self.domain_configs = domain_configs or {}
        self.on_intervention = on_intervention
        self.on_alert = on_alert

        self._state = TricksterState()
        self._analyzer = EvidenceQualityAnalyzer()
        self._detector = HollowConsensusDetector(
            min_quality_threshold=self.config.min_quality_threshold,
        )
        self._cross_analyzer = CrossProposalAnalyzer()

    def resolve_config(self, domain: str | None = None) -> TricksterConfig:
        """Resolve the effective config for a given domain.

        Args:
            domain: Domain name (e.g. ``"medical"``, ``"legal"``).
                Falls back to default config if not found.

        Returns:
            TricksterConfig for the specified domain, or the default.
        """
        if domain and domain in self.domain_configs:
            return self.domain_configs[domain]
        return self.config

    def check_and_intervene(  # noqa: C901 - Preserve intervention priority and cooldown ordering.
        self,
        responses: dict[str, str],
        convergence_similarity: float,
        round_num: int,
    ) -> TricksterIntervention | None:
        """Check evidence quality and potentially intervene.

        This is the main entry point, called after each debate round.

        Args:
            responses: Agent name -> response text.
            convergence_similarity: Semantic similarity from ConvergenceDetector.
            round_num: Current round number.

        Returns:
            TricksterIntervention if intervention needed, None otherwise.
        """
        # Analyze evidence quality
        quality_scores = self._analyzer.analyze_batch(responses, round_num)
        self._state.quality_history.append(quality_scores)

        # Check for hollow consensus
        alert = self._detector.check(responses, convergence_similarity, round_num)
        self._state.hollow_alerts.append(alert)

        if self.on_alert and alert.detected:
            self.on_alert(alert)

        # Cross-proposal analysis — run when responses show any convergence OR
        # when evidence quality is poor enough to warrant proactive checking.
        # The original gate of 0.6 was too strict: mock/canned agents produce
        # low SequenceMatcher similarity even when reaching voting consensus.
        # We now also run cross-analysis whenever average evidence quality is
        # below the configured threshold (the whole point of the Trickster).
        cross_analysis: CrossProposalAnalysis | None = None
        avg_quality = (
            sum(s.overall_quality for s in quality_scores.values()) / len(quality_scores)
            if quality_scores
            else 1.0
        )
        should_cross_analyze = (
            convergence_similarity > 0.6 or avg_quality < self.config.min_quality_threshold
        )
        if should_cross_analyze:
            cross_analysis = self._cross_analyzer.analyze(responses)

            # Check for evidence gaps
            if cross_analysis.evidence_gaps:
                intervention = self._create_evidence_gap_intervention(cross_analysis, round_num)
                if intervention:
                    return self._record_intervention(intervention, round_num)

            # Check for echo chamber
            if cross_analysis.redundancy_score > 0.7:
                intervention = self._create_echo_chamber_intervention(cross_analysis, round_num)
                if intervention:
                    return self._record_intervention(intervention, round_num)

        # Decide on intervention based on traditional hollow consensus check
        if not alert.detected:
            logger.debug("trickster_pass round=%d reason=quality_acceptable", round_num)
            return None

        if alert.severity < self.config.hollow_detection_threshold:
            logger.debug(
                "trickster_pass round=%d reason=below_threshold severity=%.2f",
                round_num,
                alert.severity,
            )
            return None

        # Check cooldown
        rounds_since = round_num - self._state.last_intervention_round
        if rounds_since < self.config.intervention_cooldown_rounds:
            logger.debug("trickster_cooldown round=%d rounds_since=%d", round_num, rounds_since)
            return None

        # Check max interventions
        if self._state.total_interventions >= self.config.max_interventions_total:
            logger.debug(
                "trickster_limit round=%d total=%d",
                round_num,
                self._state.total_interventions,
            )
            return None

        # Create intervention
        intervention = self._create_intervention(alert, quality_scores, round_num, cross_analysis)
        return self._record_intervention(intervention, round_num)

    def _record_intervention(
        self,
        intervention: TricksterIntervention,
        round_num: int,
    ) -> TricksterIntervention | None:
        """Record an intervention and update state.

        Returns the intervention if it was recorded, or ``None`` if it was
        suppressed by cooldown or max-intervention limits.
        """
        # Check cooldown
        rounds_since = round_num - self._state.last_intervention_round
        if rounds_since < self.config.intervention_cooldown_rounds:
            logger.debug("trickster_cooldown round=%d rounds_since=%d", round_num, rounds_since)
            return None

        # Check max interventions
        if self._state.total_interventions >= self.config.max_interventions_total:
            logger.debug(
                "trickster_limit round=%d total=%d",
                round_num,
                self._state.total_interventions,
            )
            return None

        self._state.interventions.append(intervention)
        self._state.last_intervention_round = round_num
        self._state.total_interventions += 1

        logger.info(
            "trickster_intervene round=%d type=%s targets=%s",
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

    def _build_evidence_gap_challenge(self, cross_analysis: CrossProposalAnalysis) -> str:
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

    def _build_echo_chamber_challenge(self, cross_analysis: CrossProposalAnalysis) -> str:
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
        sorted_agents = sorted(alert.agent_scores.items(), key=lambda x: x[1])
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

        challenge_text = self._build_challenge(alert, evidence_gaps, target_agents)

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
                    "cross_analysis_gaps_count": len(cross_analysis.evidence_gaps),
                }
            )

        return TricksterIntervention(
            intervention_type=InterventionType.CHALLENGE_PROMPT,
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

        if alert.recommended_challenges:
            lines.append("### Specific Challenges:")
            for challenge in alert.recommended_challenges:
                lines.append(f"- {challenge}")
            lines.append("")

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

    def reset(self) -> None:
        """Reset trickster state for a new debate."""
        self._state = TricksterState()


__all__ = [
    "InterventionType",
    "TricksterIntervention",
    "TricksterConfig",
    "TricksterState",
    "EvidencePoweredTrickster",
]
