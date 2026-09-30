"""Cross-Proposal Analyzer for multi-agent evidence validation.

This module analyzes evidence patterns across multiple agent proposals to detect:
- Shared evidence (same sources cited by multiple agents)
- Contradictory evidence (opposite conclusions from similar evidence)
- Evidence gaps (claims in consensus but no evidence from any agent)
- Echo chamber patterns (agents citing each other without external validation)

Key insight: When agents converge, they should converge on EVIDENCE, not just
conclusions.  If they agree but cite different (or no) evidence, the consensus
is hollow.

Uses only the standard library (regex-based analysis via
:class:`EvidenceQualityAnalyzer`) — no ML dependencies required.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TypedDict

from aragora_debate.evidence import EvidenceQualityAnalyzer, EvidenceQualityScore

logger = logging.getLogger(__name__)


class _EvidenceGroup(TypedDict):
    text: str
    agents: set[str]


@dataclass
class SharedEvidence:
    """Evidence cited by multiple agents."""

    evidence_text: str
    evidence_type: str  # e.g. "citation", "data", "example"
    agents: list[str]  # Agents who cited this evidence
    claims_supported: list[str]  # Claims this evidence supports

    @property
    def agent_count(self) -> int:
        """Number of agents citing this evidence."""
        return len(self.agents)


@dataclass
class Contradiction:
    """Contradictory evidence between agents."""

    agent1: str
    agent2: str
    topic: str  # The topic/claim being contradicted
    evidence1: str
    evidence2: str
    description: str  # Human-readable description


@dataclass
class EvidenceGap:
    """A claim made without supporting evidence."""

    claim: str
    agents_making_claim: list[str]
    gap_severity: float  # 0-1, higher = more severe


@dataclass
class CrossProposalAnalysis:
    """Complete analysis of evidence patterns across proposals."""

    # Positive signals
    shared_evidence: list[SharedEvidence]
    evidence_corroboration_score: float  # 0-1, how much evidence is shared

    # Warning signals
    contradictory_evidence: list[Contradiction]
    evidence_gaps: list[EvidenceGap]

    # Echo chamber detection
    redundancy_score: float  # 0-1, how much agents echo each other
    unique_evidence_sources: int  # Number of distinct evidence sources
    total_evidence_sources: int  # Total evidence citations

    # Per-agent analysis
    agent_coverage: dict[str, float]  # agent -> coverage score
    weakest_agent: str | None  # Agent with lowest evidence quality

    @property
    def has_concerns(self) -> bool:
        """Whether there are significant evidence concerns."""
        return (
            len(self.evidence_gaps) > 0
            or len(self.contradictory_evidence) > 0
            or self.redundancy_score > 0.7
        )

    @property
    def top_concern(self) -> str | None:
        """Get the most significant concern."""
        if self.evidence_gaps:
            return f"Evidence gap: {self.evidence_gaps[0].claim[:80]}..."
        if self.contradictory_evidence:
            c = self.contradictory_evidence[0]
            return f"Contradiction between {c.agent1} and {c.agent2} on {c.topic}"
        if self.redundancy_score > 0.7:
            return f"Echo chamber: {self.redundancy_score:.0%} redundancy"
        return None


class CrossProposalAnalyzer:
    """Analyzes evidence patterns across converging agent proposals.

    This is the key component for detecting hollow consensus. When multiple
    agents agree on a conclusion, this analyzer checks whether they're
    agreeing on evidence too, or just echoing each other.

    Uses regex-based evidence detection (via :class:`EvidenceQualityAnalyzer`)
    instead of ML-based semantic analysis — zero external dependencies.

    Usage::

        analyzer = CrossProposalAnalyzer()

        proposals = {
            "claude": "We should use caching. According to [1], it improves...",
            "gpt": "Caching is the best approach. Studies show...",
            "gemini": "I agree caching helps performance.",
        }

        analysis = analyzer.analyze(proposals)

        if analysis.has_concerns:
            print(f"Warning: {analysis.top_concern}")
    """

    def __init__(
        self,
        min_redundancy_similarity: float = 0.7,
        min_claim_overlap: float = 0.5,
    ) -> None:
        self._evidence_analyzer = EvidenceQualityAnalyzer()
        self.min_redundancy_similarity = min_redundancy_similarity
        self.min_claim_overlap = min_claim_overlap

    def analyze(self, proposals: dict[str, str]) -> CrossProposalAnalysis:
        """Analyze evidence patterns across multiple agent proposals.

        Args:
            proposals: Dict of agent name -> proposal text.

        Returns:
            CrossProposalAnalysis with complete analysis.
        """
        if not proposals or len(proposals) < 2:
            return self._empty_analysis()

        # Analyze evidence quality for each agent
        quality_scores = self._evidence_analyzer.analyze_batch(proposals)

        # Extract per-agent evidence
        agent_evidence = self._extract_agent_evidence(proposals, quality_scores)

        # Find shared evidence
        shared = self._find_shared_evidence(agent_evidence)

        # Find contradictions
        contradictions = self._find_contradictions(proposals)

        # Find evidence gaps
        gaps = self._find_evidence_gaps(proposals, quality_scores)

        # Calculate redundancy
        redundancy, unique, total = self._calculate_redundancy(agent_evidence)

        # Corroboration score
        corroboration = self._calculate_corroboration(shared, len(proposals))

        # Per-agent coverage
        coverage = {agent: score.overall_quality for agent, score in quality_scores.items()}

        weakest = min(coverage, key=lambda k: coverage[k]) if coverage else None

        return CrossProposalAnalysis(
            shared_evidence=shared,
            evidence_corroboration_score=corroboration,
            contradictory_evidence=contradictions,
            evidence_gaps=gaps,
            redundancy_score=redundancy,
            unique_evidence_sources=unique,
            total_evidence_sources=total,
            agent_coverage=coverage,
            weakest_agent=weakest,
        )

    def _empty_analysis(self) -> CrossProposalAnalysis:
        """Return empty analysis for edge cases."""
        return CrossProposalAnalysis(
            shared_evidence=[],
            evidence_corroboration_score=0.0,
            contradictory_evidence=[],
            evidence_gaps=[],
            redundancy_score=0.0,
            unique_evidence_sources=0,
            total_evidence_sources=0,
            agent_coverage={},
            weakest_agent=None,
        )

    def _extract_agent_evidence(
        self,
        proposals: dict[str, str],
        quality_scores: dict[str, EvidenceQualityScore],
    ) -> dict[str, list[str]]:
        """Extract evidence text snippets per agent using markers."""
        agent_evidence: dict[str, list[str]] = {}

        for agent, text in proposals.items():
            score = quality_scores[agent]
            evidence_texts: list[str] = []
            for marker in score.evidence_markers:
                normalized = self._normalize_evidence(marker.text)
                if normalized:
                    evidence_texts.append(normalized)
            agent_evidence[agent] = evidence_texts

        return agent_evidence

    def _find_shared_evidence(
        self,
        agent_evidence: dict[str, list[str]],
    ) -> list[SharedEvidence]:
        """Find evidence cited by multiple agents."""
        evidence_map: dict[str, _EvidenceGroup] = {}

        for agent, evidence_list in agent_evidence.items():
            for evidence_text in evidence_list:
                if evidence_text not in evidence_map:
                    evidence_map[evidence_text] = {
                        "text": evidence_text,
                        "agents": set(),
                    }
                evidence_map[evidence_text]["agents"].add(agent)

        shared = []
        for data in evidence_map.values():
            if len(data["agents"]) >= 2:
                shared.append(
                    SharedEvidence(
                        evidence_text=data["text"],
                        evidence_type="mixed",
                        agents=sorted(data["agents"]),
                        claims_supported=[],
                    )
                )

        return shared

    def _find_contradictions(
        self,
        proposals: dict[str, str],
    ) -> list[Contradiction]:
        """Find contradictory evidence between agents using word overlap."""
        contradictions = []
        agents = list(proposals.keys())

        # Extract claim-like sentences per agent
        agent_claims: dict[str, list[str]] = {}
        for agent, text in proposals.items():
            sentences = re.split(r"[.!?]+", text)
            claims = [
                s.strip()
                for s in sentences
                if len(s.strip()) > 20 and not s.strip().startswith(("?", "What", "How", "Why"))
            ]
            agent_claims[agent] = claims

        for i, a1 in enumerate(agents):
            for a2 in agents[i + 1 :]:
                for c1 in agent_claims.get(a1, []):
                    for c2 in agent_claims.get(a2, []):
                        claim_sim = self._text_similarity(c1, c2)
                        # Similar topic but check for negation/opposition
                        if 0.2 < claim_sim < 0.6 and self._has_negation_diff(c1, c2):
                            topic = self._extract_topic(c1, c2)
                            contradictions.append(
                                Contradiction(
                                    agent1=a1,
                                    agent2=a2,
                                    topic=topic,
                                    evidence1=c1[:200],
                                    evidence2=c2[:200],
                                    description=(f"{a1} and {a2} have opposing views on {topic}"),
                                )
                            )

        return contradictions[:3]

    def _find_evidence_gaps(  # noqa: C901 - Keep claim matching and evidence scoring together.
        self,
        proposals: dict[str, str],
        quality_scores: dict[str, EvidenceQualityScore],
    ) -> list[EvidenceGap]:
        """Find claims made without supporting evidence."""
        gaps = []

        # Extract claim sentences from each agent
        claim_map: dict[str, list[str]] = {}

        for agent, text in proposals.items():
            sentences = re.split(r"[.!?]+", text)
            claims = [
                s.strip()
                for s in sentences
                if len(s.strip()) > 25 and not s.strip().startswith(("?", "What", "How", "Why"))
            ]
            claim_map[agent] = claims

        # Find claims that appear across agents (similar wording)
        # but have no evidence backing
        all_agents = list(proposals.keys())
        seen_claims: set[str] = set()

        for i, a1 in enumerate(all_agents):
            for claim1 in claim_map.get(a1, []):
                norm1 = self._normalize_evidence(claim1)
                if norm1 in seen_claims:
                    continue

                # Check if similar claim exists in other agents
                claiming_agents = [a1]
                for a2 in all_agents[i + 1 :]:
                    for claim2 in claim_map.get(a2, []):
                        if self._text_similarity(claim1, claim2) > self.min_claim_overlap:
                            claiming_agents.append(a2)
                            break

                # Only flag as gap if multiple agents make similar claims
                if len(claiming_agents) >= 2:
                    # Check if any of these agents provided evidence near this claim
                    has_evidence = False
                    for agent in claiming_agents:
                        score = quality_scores[agent]
                        if score.citation_density > 0.3:
                            has_evidence = True
                            break

                    if not has_evidence:
                        severity = len(claiming_agents) / len(all_agents)
                        gaps.append(
                            EvidenceGap(
                                claim=claim1[:200],
                                agents_making_claim=claiming_agents,
                                gap_severity=severity,
                            )
                        )
                        seen_claims.add(norm1)

        gaps.sort(key=lambda g: g.gap_severity, reverse=True)
        return gaps[:5]

    def _calculate_redundancy(
        self,
        agent_evidence: dict[str, list[str]],
    ) -> tuple[float, int, int]:
        """Calculate redundancy score (echo chamber detection).

        Returns:
            (redundancy_score, unique_sources, total_sources)
        """
        all_evidence: list[str] = []
        unique_evidence: set[str] = set()

        for evidence_list in agent_evidence.values():
            for ev in evidence_list:
                all_evidence.append(ev)
                unique_evidence.add(ev)

        total = len(all_evidence)
        unique = len(unique_evidence)

        if total == 0:
            return 0.0, 0, 0

        redundancy = 1.0 - (unique / total)
        return redundancy, unique, total

    def _calculate_corroboration(
        self,
        shared: list[SharedEvidence],
        num_agents: int,
    ) -> float:
        """Calculate evidence corroboration score."""
        if not shared or num_agents < 2:
            return 0.0

        max_sharing = sum(s.agent_count for s in shared)
        potential_sharing = len(shared) * num_agents

        return max_sharing / potential_sharing if potential_sharing > 0 else 0.0

    @staticmethod
    def _normalize_evidence(text: str) -> str:
        """Normalize evidence text for comparison."""
        normalized = re.sub(r"\s+", " ", text.lower().strip())
        normalized = re.sub(r"[^\w\s]", "", normalized)
        return normalized if len(normalized) > 5 else ""

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """Simple text similarity using Jaccard word overlap."""
        words1 = set(re.findall(r"\b\w{4,}\b", text1.lower()))
        words2 = set(re.findall(r"\b\w{4,}\b", text2.lower()))

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    @staticmethod
    def _has_negation_diff(text1: str, text2: str) -> bool:
        """Check if texts differ by negation patterns."""
        negation_words = {
            "not",
            "no",
            "never",
            "don't",
            "doesn't",
            "shouldn't",
            "won't",
            "can't",
            "isn't",
            "aren't",
            "without",
            "lack",
            "avoid",
            "instead",
            "rather",
            "however",
            "but",
            "although",
        }

        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        neg1 = words1 & negation_words
        neg2 = words2 & negation_words

        return neg1 != neg2

    @staticmethod
    def _extract_topic(claim1: str, claim2: str) -> str:
        """Extract common topic from two claims."""
        words1 = set(re.findall(r"\b\w{4,}\b", claim1.lower()))
        words2 = set(re.findall(r"\b\w{4,}\b", claim2.lower()))
        common = words1 & words2

        if common:
            return " ".join(sorted(common)[:3])
        return "related topic"


__all__ = [
    "SharedEvidence",
    "Contradiction",
    "EvidenceGap",
    "CrossProposalAnalysis",
    "CrossProposalAnalyzer",
]
