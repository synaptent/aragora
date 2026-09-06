"""Evidence Quality Scoring for Debate Rigor.

This module implements evidence quality metrics to detect "hollow consensus" -
when agents agree without substantive backing. It scores:
- Citation density (claims backed by sources)
- Specificity (concrete details vs vague statements)
- Evidence diversity (multiple evidence types)
- Temporal relevance (fresh data vs stale references)

Used by the convergence detector and trickster challenger.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class EvidenceType(Enum):
    """Types of evidence that can back a claim."""

    CITATION = "citation"  # Academic/formal reference
    DATA = "data"  # Numbers, statistics, metrics
    EXAMPLE = "example"  # Concrete case or instance
    TOOL_OUTPUT = "tool_output"  # Code execution, API response
    QUOTE = "quote"  # Direct quotation
    REASONING = "reasoning"  # Logical argument chain
    NONE = "none"  # No backing evidence


@dataclass
class EvidenceMarker:
    """A detected piece of evidence in agent response."""

    evidence_type: EvidenceType
    text: str
    position: int  # Character position in response
    confidence: float  # 0-1, how confident in detection


@dataclass
class EvidenceQualityScore:
    """Comprehensive evidence quality assessment for an agent response."""

    agent: str
    round_num: int

    # Core metrics (0-1 scale)
    citation_density: float = 0.0  # Fraction of claims with citations
    specificity_score: float = 0.0  # Concrete vs vague language
    evidence_diversity: float = 0.0  # Range of evidence types used
    temporal_relevance: float = 1.0  # Freshness of references
    logical_chain_score: float = 0.0  # Reasoning coherence

    # Derived overall score
    overall_quality: float = 0.0

    # Supporting data
    evidence_markers: list[EvidenceMarker] = field(default_factory=list)
    claim_count: int = 0
    backed_claim_count: int = 0
    vague_phrase_count: int = 0
    specific_phrase_count: int = 0

    def compute_overall(self) -> float:
        """Compute weighted overall quality score."""
        weights = {
            "citation_density": 0.25,
            "specificity_score": 0.25,
            "evidence_diversity": 0.20,
            "temporal_relevance": 0.10,
            "logical_chain_score": 0.20,
        }
        self.overall_quality = (
            weights["citation_density"] * self.citation_density
            + weights["specificity_score"] * self.specificity_score
            + weights["evidence_diversity"] * self.evidence_diversity
            + weights["temporal_relevance"] * self.temporal_relevance
            + weights["logical_chain_score"] * self.logical_chain_score
        )
        return self.overall_quality


# Patterns for evidence detection
CITATION_PATTERNS = [
    r"\[[\d,\s]+\]",  # [1], [1, 2]
    r"\([\w\s]+,?\s*\d{4}\)",  # (Author 2024)
    r"according to\s+[\w\s]+",  # according to X
    r"https?://\S+",  # URLs
    r"source:\s*\S+",  # source: X
]

DATA_PATTERNS = [
    r"\d+(?:\.\d+)?%",  # Percentages
    r"\$[\d,]+(?:\.\d+)?",  # Currency
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:ms|s|seconds|minutes|hours|days)",  # Time metrics
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:KB|MB|GB|TB)",  # Size metrics
    r"(?:increased|decreased|improved|reduced)\s+(?:by\s+)?\d+",  # Change metrics
]

EXAMPLE_PATTERNS = [
    r"for example",
    r"for instance",
    r"such as\s+\w+",
    r"e\.g\.",
    r"specifically,",
    r"in practice,",
    r"case in point",
]

VAGUE_PHRASES = [
    "generally",
    "typically",
    "usually",
    "often",
    "sometimes",
    "might",
    "could potentially",
    "may or may not",
    "it depends",
    "in some cases",
    "various factors",
    "many considerations",
    "significant impact",
    "important aspects",
    "key elements",
    "best practices",
    "industry standard",
    "common approach",
]

SPECIFIC_INDICATORS = [
    r"\d+(?:\.\d+)?",  # Any number
    r"specifically",
    r"precisely",
    r"exactly",
    r"measured at",
    r"observed in",
    r"documented in",
    r"tested with",
    r"verified by",
]

REASONING_CONNECTORS = [
    "therefore",
    "thus",
    "consequently",
    "because",
    "since",
    "given that",
    "it follows that",
    "this implies",
    "as a result",
    "hence",
]


class EvidenceQualityAnalyzer:
    """Analyzes agent responses for evidence quality.

    This is the core component that detects hollow consensus by measuring
    the substantive backing behind agent statements.
    """

    def __init__(
        self,
        citation_weight: float = 0.25,
        specificity_weight: float = 0.25,
        diversity_weight: float = 0.20,
        temporal_weight: float = 0.10,
        reasoning_weight: float = 0.20,
    ):
        """Initialize analyzer with custom weights."""
        self.weights = {
            "citation": citation_weight,
            "specificity": specificity_weight,
            "diversity": diversity_weight,
            "temporal": temporal_weight,
            "reasoning": reasoning_weight,
        }
        # Compile patterns for performance
        self._citation_re = [re.compile(p, re.IGNORECASE) for p in CITATION_PATTERNS]
        self._data_re = [re.compile(p, re.IGNORECASE) for p in DATA_PATTERNS]
        self._example_re = [re.compile(p, re.IGNORECASE) for p in EXAMPLE_PATTERNS]
        self._specific_re = [re.compile(p, re.IGNORECASE) for p in SPECIFIC_INDICATORS]
        self._reasoning_re = [re.compile(rf"\b{p}\b", re.IGNORECASE) for p in REASONING_CONNECTORS]

    def analyze(
        self,
        response: str,
        agent: str,
        round_num: int = 0,
    ) -> EvidenceQualityScore:
        """Analyze a single agent response for evidence quality.

        Args:
            response: The agent's response text
            agent: Agent identifier
            round_num: Current debate round

        Returns:
            EvidenceQualityScore with all metrics computed
        """
        score = EvidenceQualityScore(agent=agent, round_num=round_num)

        if not response:
            return score

        # Detect evidence markers
        score.evidence_markers = self._detect_evidence(response)

        # Compute individual metrics
        score.citation_density = self._compute_citation_density(response, score)
        score.specificity_score = self._compute_specificity(response, score)
        score.evidence_diversity = self._compute_diversity(score)
        score.logical_chain_score = self._compute_reasoning_chain(response)
        score.temporal_relevance = self._compute_temporal_relevance(response)

        # Compute overall
        score.compute_overall()

        logger.debug(
            "evidence_quality agent=%s round=%d overall=%.2f citations=%.2f specificity=%.2f",
            agent,
            round_num,
            score.overall_quality,
            score.citation_density,
            score.specificity_score,
        )

        return score

    def analyze_batch(
        self,
        responses: dict[str, str],
        round_num: int = 0,
    ) -> dict[str, EvidenceQualityScore]:
        """Analyze multiple agent responses.

        Args:
            responses: Dict of agent name to response text
            round_num: Current debate round

        Returns:
            Dict of agent name to EvidenceQualityScore
        """
        return {
            agent: self.analyze(response, agent, round_num) for agent, response in responses.items()
        }

    def _detect_evidence(self, text: str) -> list[EvidenceMarker]:
        """Detect all evidence markers in text."""
        markers = []

        # Citations
        for pattern in self._citation_re:
            for match in pattern.finditer(text):
                markers.append(
                    EvidenceMarker(
                        evidence_type=EvidenceType.CITATION,
                        text=match.group(),
                        position=match.start(),
                        confidence=0.9,
                    )
                )

        # Data/statistics
        for pattern in self._data_re:
            for match in pattern.finditer(text):
                markers.append(
                    EvidenceMarker(
                        evidence_type=EvidenceType.DATA,
                        text=match.group(),
                        position=match.start(),
                        confidence=0.85,
                    )
                )

        # Examples
        for pattern in self._example_re:
            for match in pattern.finditer(text):
                markers.append(
                    EvidenceMarker(
                        evidence_type=EvidenceType.EXAMPLE,
                        text=match.group(),
                        position=match.start(),
                        confidence=0.8,
                    )
                )

        return markers

    def _compute_citation_density(self, text: str, score: EvidenceQualityScore) -> float:
        """Compute fraction of text with citation backing."""
        sentences = re.split(r"[.!?]+", text)
        assertion_sentences = [
            s
            for s in sentences
            if len(s.strip()) > 20 and not s.strip().startswith(("?", "What", "How", "Why", "When"))
        ]
        score.claim_count = len(assertion_sentences)

        citation_markers = [
            m for m in score.evidence_markers if m.evidence_type == EvidenceType.CITATION
        ]
        score.backed_claim_count = min(len(citation_markers), score.claim_count)

        if score.claim_count == 0:
            return 0.0

        return min(1.0, score.backed_claim_count / score.claim_count)

    def _compute_specificity(self, text: str, score: EvidenceQualityScore) -> float:
        """Compute specificity score (concrete vs vague language)."""
        text_lower = text.lower()

        vague_count = sum(1 for phrase in VAGUE_PHRASES if phrase in text_lower)
        score.vague_phrase_count = vague_count

        specific_count = sum(len(pattern.findall(text)) for pattern in self._specific_re)
        score.specific_phrase_count = specific_count

        total = vague_count + specific_count
        if total == 0:
            return 0.5

        return specific_count / total

    def _compute_diversity(self, score: EvidenceQualityScore) -> float:
        """Compute evidence type diversity."""
        types_present = set(m.evidence_type for m in score.evidence_markers)
        types_present.discard(EvidenceType.NONE)

        max_types = 5  # CITATION, DATA, EXAMPLE, TOOL_OUTPUT, QUOTE
        return len(types_present) / max_types

    def _compute_reasoning_chain(self, text: str) -> float:
        """Compute logical reasoning coherence."""
        connector_count = sum(len(pattern.findall(text)) for pattern in self._reasoning_re)

        word_count = len(text.split())
        expected = max(1, word_count / 100)

        return min(1.0, connector_count / expected)

    def _compute_temporal_relevance(self, text: str) -> float:
        """Check for temporal relevance of references."""
        year_pattern = re.compile(r"\b(19|20)\d{2}\b")
        years = [int(m.group()) for m in year_pattern.finditer(text)]

        if not years:
            return 0.8

        current_year = datetime.now(timezone.utc).year
        max_age = 10

        recent_years = [y for y in years if current_year - y <= max_age]
        if not recent_years:
            return 0.3

        avg_age = sum(current_year - y for y in recent_years) / len(recent_years)
        return max(0.0, 1.0 - (avg_age / max_age))


@dataclass
class HollowConsensusAlert:
    """Alert when hollow consensus is detected."""

    detected: bool
    severity: float  # 0-1, higher = more hollow
    reason: str
    agent_scores: dict[str, float]  # Per-agent quality scores
    recommended_challenges: list[str]  # Suggested intervention prompts
    min_quality: float = 0.0
    avg_quality: float = 0.0
    quality_variance: float = 0.0


class HollowConsensusDetector:
    """Detects hollow consensus - when agents agree without substantive evidence.

    Integrates with ConvergenceDetector to add evidence quality checking
    on top of semantic similarity.
    """

    def __init__(
        self,
        min_quality_threshold: float = 0.4,
        quality_variance_threshold: float = 0.3,
        hollow_severity_weights: dict[str, float] | None = None,
    ):
        self.min_quality_threshold = min_quality_threshold
        self.quality_variance_threshold = quality_variance_threshold
        self.severity_weights = hollow_severity_weights or {
            "low_quality": 0.4,
            "high_variance": 0.3,
            "no_citations": 0.2,
            "vague_language": 0.1,
        }
        self.analyzer = EvidenceQualityAnalyzer()

    def check(  # noqa: C901 - Preserve the ordered hollow-consensus threshold checks.
        self,
        responses: dict[str, str],
        convergence_similarity: float,
        round_num: int = 0,
    ) -> HollowConsensusAlert:
        """Check for hollow consensus in converging responses.

        Args:
            responses: Dict of agent name to response text
            convergence_similarity: Semantic similarity from ConvergenceDetector
            round_num: Current debate round

        Returns:
            HollowConsensusAlert with detection result
        """
        if convergence_similarity < 0.15:
            return HollowConsensusAlert(
                detected=False,
                severity=0.0,
                reason="Not converging yet",
                agent_scores={},
                recommended_challenges=[],
            )

        quality_scores = self.analyzer.analyze_batch(responses, round_num)
        agent_quality = {agent: score.overall_quality for agent, score in quality_scores.items()}

        qualities = list(agent_quality.values())
        if not qualities:
            return HollowConsensusAlert(
                detected=False,
                severity=0.0,
                reason="No responses to analyze",
                agent_scores={},
                recommended_challenges=[],
            )

        min_quality = min(qualities)
        avg_quality = sum(qualities) / len(qualities)
        variance = (
            sum((q - avg_quality) ** 2 for q in qualities) / len(qualities)
            if len(qualities) > 1
            else 0.0
        )

        issues = []
        severity_components = []

        if avg_quality < self.min_quality_threshold:
            issues.append(f"Low evidence quality ({avg_quality:.0%})")
            severity_components.append(
                ("low_quality", 1.0 - avg_quality / self.min_quality_threshold)
            )

        if variance > self.quality_variance_threshold:
            issues.append(f"Uneven evidence quality (variance={variance:.2f})")
            severity_components.append(
                ("high_variance", min(1.0, variance / self.quality_variance_threshold))
            )

        no_citation_agents = []
        vague_agents = []
        for agent, score in quality_scores.items():
            if score.citation_density < 0.2:
                issues.append(f"{agent} lacks citations")
                no_citation_agents.append(agent)
            if score.specificity_score < 0.3:
                issues.append(f"{agent} uses vague language")
                vague_agents.append(agent)

        # Add severity for widespread citation absence
        if no_citation_agents:
            ratio = len(no_citation_agents) / len(quality_scores)
            severity_components.append(("no_citations", ratio))

        # Add severity for widespread vague language
        if vague_agents:
            ratio = len(vague_agents) / len(quality_scores)
            severity_components.append(("vague_language", ratio))

        severity = 0.0
        for component, value in severity_components:
            severity += self.severity_weights.get(component, 0.1) * value
        severity = min(1.0, severity)

        challenges = self._generate_challenges(quality_scores, issues)

        # Hollow consensus can be detected at lower convergence if evidence
        # quality is very poor (agents agree on nothing substantive).  Scale
        # the convergence bar down proportionally to how bad the quality is:
        #   avg_quality >= threshold  -> need convergence > 0.7  (original)
        #   avg_quality == 0          -> need convergence > 0.15
        quality_ratio = (
            min(1.0, avg_quality / self.min_quality_threshold)
            if self.min_quality_threshold > 0
            else 1.0
        )
        convergence_bar = 0.15 + 0.55 * quality_ratio  # range [0.15, 0.70]
        detected = severity > 0.1 and convergence_similarity > convergence_bar
        reason = "; ".join(issues) if issues else "Evidence quality acceptable"

        alert = HollowConsensusAlert(
            detected=detected,
            severity=severity,
            reason=reason,
            agent_scores=agent_quality,
            recommended_challenges=challenges,
            min_quality=min_quality,
            avg_quality=avg_quality,
            quality_variance=variance,
        )

        if detected:
            logger.warning(
                "hollow_consensus_detected severity=%.2f avg_quality=%.2f convergence=%.2f",
                severity,
                avg_quality,
                convergence_similarity,
            )

        return alert

    def _generate_challenges(
        self,
        quality_scores: dict[str, EvidenceQualityScore],
        issues: list[str],
    ) -> list[str]:
        """Generate challenge prompts based on quality gaps."""
        challenges = []

        low_citation_agents = [
            agent for agent, score in quality_scores.items() if score.citation_density < 0.2
        ]
        if low_citation_agents:
            challenges.append(
                f"Challenge to {', '.join(low_citation_agents)}: "
                "What specific sources or data support your position? "
                "Please provide concrete references."
            )

        vague_agents = [
            agent for agent, score in quality_scores.items() if score.specificity_score < 0.3
        ]
        if vague_agents:
            challenges.append(
                f"Challenge to {', '.join(vague_agents)}: "
                "Your response contains vague language. "
                "Can you provide specific numbers, examples, or measurable outcomes?"
            )

        weak_reasoning = [
            agent for agent, score in quality_scores.items() if score.logical_chain_score < 0.3
        ]
        if weak_reasoning:
            challenges.append(
                f"Challenge to {', '.join(weak_reasoning)}: "
                "How does your conclusion follow from your premises? "
                "Please explain the logical chain."
            )

        if not challenges and issues:
            challenges.append(
                "The current consensus appears to lack substantive backing. "
                "Before finalizing, please each provide concrete evidence "
                "supporting your position."
            )

        return challenges[:3]


__all__ = [
    "EvidenceType",
    "EvidenceMarker",
    "EvidenceQualityScore",
    "EvidenceQualityAnalyzer",
    "HollowConsensusAlert",
    "HollowConsensusDetector",
]
