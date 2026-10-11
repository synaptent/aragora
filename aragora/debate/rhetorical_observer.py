"""
Rhetorical Analysis Observer - Passive debate commentary for engagement.

Observes debates and provides commentary on rhetorical patterns:
- Pattern detection (concession, rebuttal, synthesis)
- Audience-friendly insights
- Debate dynamics tracking
- Non-interference with debate flow

Inspired by nomic loop debate consensus on audience engagement.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class RhetoricalPattern(Enum):
    """Rhetorical patterns to detect."""

    CONCESSION = "concession"
    REBUTTAL = "rebuttal"
    SYNTHESIS = "synthesis"
    APPEAL_TO_AUTHORITY = "appeal_to_authority"
    APPEAL_TO_EVIDENCE = "appeal_to_evidence"
    TECHNICAL_DEPTH = "technical_depth"
    RHETORICAL_QUESTION = "rhetorical_question"
    ANALOGY = "analogy"
    QUALIFICATION = "qualification"


@dataclass
class RhetoricalObservation:
    """A rhetorical observation about debate content."""

    pattern: RhetoricalPattern
    agent: str
    round_num: int
    confidence: float
    excerpt: str
    audience_commentary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern.value,
            "agent": self.agent,
            "round_num": self.round_num,
            "confidence": self.confidence,
            "excerpt": self.excerpt,
            "audience_commentary": self.audience_commentary,
            "timestamp": self.timestamp,
        }


class FallacyType(Enum):
    """Logical fallacies detectable by structural analysis."""

    AD_HOMINEM = "ad_hominem"
    STRAW_MAN = "straw_man"
    CIRCULAR_REASONING = "circular_reasoning"
    FALSE_DILEMMA = "false_dilemma"
    APPEAL_TO_IGNORANCE = "appeal_to_ignorance"
    SLIPPERY_SLOPE = "slippery_slope"
    RED_HERRING = "red_herring"


@dataclass
class FallacyDetection:
    """A detected logical fallacy in debate content."""

    fallacy_type: FallacyType
    confidence: float
    excerpt: str
    explanation: str
    agent: str = ""
    round_num: int = 0

    def to_dict(self) -> dict:
        return {
            "fallacy_type": self.fallacy_type.value,
            "confidence": self.confidence,
            "excerpt": self.excerpt,
            "explanation": self.explanation,
            "agent": self.agent,
            "round_num": self.round_num,
        }


@dataclass
class PremiseChain:
    """A chain of premises leading to a conclusion."""

    premises: list[str]
    conclusion: str
    agent: str
    confidence: float
    has_gap: bool = False  # True if unsupported leap detected

    def to_dict(self) -> dict:
        return {
            "premises": self.premises,
            "conclusion": self.conclusion,
            "agent": self.agent,
            "confidence": self.confidence,
            "has_gap": self.has_gap,
        }


@dataclass
class ClaimRelationship:
    """A relationship between two claims detected via structural analysis."""

    source_claim: str
    target_claim: str
    relation: str  # "supports", "contradicts", "refines"
    confidence: float
    agent: str = ""

    def to_dict(self) -> dict:
        return {
            "source_claim": self.source_claim,
            "target_claim": self.target_claim,
            "relation": self.relation,
            "confidence": self.confidence,
            "agent": self.agent,
        }


@dataclass
class StructuralAnalysisResult:
    """Result of structural argument analysis on a piece of content."""

    fallacies: list[FallacyDetection] = field(default_factory=list)
    premise_chains: list[PremiseChain] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    contradictions: list[tuple[str, str]] = field(default_factory=list)
    claim_relationships: list[ClaimRelationship] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "fallacies": [f.to_dict() for f in self.fallacies],
            "premise_chains": [p.to_dict() for p in self.premise_chains],
            "unsupported_claims": self.unsupported_claims,
            "contradictions": list(self.contradictions),
            "claim_relationships": [r.to_dict() for r in self.claim_relationships],
            "confidence": self.confidence,
        }


class StructuralAnalyzer:
    """
    Structural argument analyzer for debate content.

    Detects logical fallacies, analyzes premise chains, identifies
    unsupported claims, and tracks claim relationships. Uses the
    ClaimType and RelationType enums from aragora.reasoning.claims
    for consistent typing.

    This analyzer complements the keyword-based detection in
    RhetoricalAnalysisObserver with deeper structural analysis.
    """

    # Fallacy detection patterns (keyword + regex indicators)
    FALLACY_INDICATORS: dict[FallacyType, dict[str, Any]] = {
        FallacyType.AD_HOMINEM: {
            "keywords": [
                "you always",
                "you never",
                "your bias",
                "you clearly don't",
                "incompetent",
                "you don't understand",
                "your ignorance",
                "people like you",
                "your kind",
            ],
            "patterns": [
                r"\byou('re| are) (just|only|clearly|obviously) (wrong|biased|ignorant)\b",
                r"\b(your|their) (lack of|limited) (understanding|knowledge|experience)\b",
                r"\b(anyone|someone) who (thinks|believes|says) that\b.*\b(foolish|stupid|naive)\b",
            ],
            "explanation": "Attacks the person rather than their argument",
        },
        FallacyType.STRAW_MAN: {
            "keywords": [
                "so you're saying",
                "what you really mean",
                "you're basically arguing",
                "in other words you think",
                "so your position is",
            ],
            "patterns": [
                r"\bso (you're|you are) (saying|arguing|claiming)\b",
                r"\bwhat you('re| are) really (saying|meaning)\b",
                r"\byou('re| are) basically (saying|arguing)\b",
            ],
            "explanation": "Misrepresents the opponent's argument to make it easier to attack",
        },
        FallacyType.CIRCULAR_REASONING: {
            "keywords": [
                "because it is",
                "it's true because",
                "obviously true",
                "self-evident",
                "goes without saying",
            ],
            "patterns": [
                r"\b(this|it|that) is (true|correct|right) because (it|this|that) is (true|correct|right)\b",
                r"\b(we know|it's clear) .{0,40} because .{0,40} (we know|it's clear)\b",
                r"\bby definition\b.*\btherefore\b.*\bby definition\b",
            ],
            "explanation": "The conclusion is used as a premise, creating circular logic",
        },
        FallacyType.FALSE_DILEMMA: {
            "keywords": [
                "either we",
                "the only option",
                "the only choice",
                "no other way",
                "only two options",
                "must choose between",
                "there are only",
            ],
            "patterns": [
                r"\b(either|the only) .{0,30} or .{0,30} (nothing|no other|that's it)\b",
                r"\bwe (must|have to) (choose|pick|decide) between\b",
                r"\bthere (are|is) (only|just) (two|2) (options?|choices?|ways?|alternatives?)\b",
                r"\b(it's|this is) (either|all) or nothing\b",
            ],
            "explanation": "Presents only two options when more alternatives exist",
        },
        FallacyType.APPEAL_TO_IGNORANCE: {
            "keywords": [
                "no one has proven",
                "can't be disproven",
                "hasn't been shown",
                "no evidence against",
                "absence of evidence",
            ],
            "patterns": [
                r"\bno (one|body) has (proven|shown|demonstrated) (otherwise|it wrong)\b",
                r"\b(can't|cannot|hasn't been) (be )?(disproven|refuted)\b",
                r"\b(since|because) (there is|there's) no (evidence|proof) (against|to the contrary)\b",
                r"\babsence of (evidence|proof) .{0,20} (evidence|proof) of absence\b",
            ],
            "explanation": "Claims something is true because it hasn't been proven false (or vice versa)",
        },
        FallacyType.SLIPPERY_SLOPE: {
            "keywords": [
                "next thing you know",
                "before you know it",
                "will inevitably lead",
                "it's a slippery slope",
                "where does it end",
                "opens the door to",
                "opens the floodgates",
            ],
            "patterns": [
                r"\bif we .{0,40} then .{0,40} then .{0,40} (eventually|ultimately|finally)\b",
                r"\b(will|would) (inevitably|eventually|ultimately) (lead|result) (in|to)\b",
                r"\b(this|that|it) (opens|is) (the door|a gateway|a slippery slope)\b",
                r"\bnext thing you know\b",
            ],
            "explanation": "Assumes one action will inevitably lead to extreme consequences without justification",
        },
        FallacyType.RED_HERRING: {
            "keywords": [
                "speaking of which",
                "that reminds me",
                "on a related note",
                "what about",
                "but what about",
                "let's not forget",
            ],
            "patterns": [
                r"\bbut (what about|how about|consider)\b",
                r"\blet('s| us) (not forget|also consider|talk about)\b",
                r"\b(speaking|talking) of (which|that)\b.*\b(different|another|unrelated)\b",
            ],
            "explanation": "Introduces an irrelevant topic to divert attention from the argument",
        },
    }

    # Premise chain indicators
    _PREMISE_MARKERS = re.compile(
        r"\b(because|since|given that|as|due to|owing to|considering that)\b", re.I
    )
    _CONCLUSION_MARKERS = re.compile(
        r"\b(therefore|thus|hence|so|consequently|as a result|it follows that|"
        r"we can conclude|this means|this shows|this proves|this implies)\b",
        re.I,
    )
    _SUPPORT_MARKERS = re.compile(
        r"\b(supports|confirms|validates|reinforces|backs up|corroborates|"
        r"is consistent with|aligns with|agrees with)\b",
        re.I,
    )
    _CONTRADICTION_MARKERS = re.compile(
        r"\b(contradicts|conflicts with|is inconsistent with|opposes|"
        r"undermines|is at odds with|clashes with|negates)\b",
        re.I,
    )
    _REFINEMENT_MARKERS = re.compile(
        r"\b(refines|clarifies|extends|elaborates on|adds to|"
        r"builds on|expands on|modifies|qualifies)\b",
        re.I,
    )

    def __init__(self) -> None:
        """Initialize the structural analyzer."""
        self._claim_history: list[dict[str, Any]] = []
        self._all_results: list[StructuralAnalysisResult] = []

    def analyze(
        self,
        content: str,
        agent: str = "",
        round_num: int = 0,
    ) -> StructuralAnalysisResult:
        """
        Perform structural analysis on debate content.

        Args:
            content: Text content to analyze
            agent: Name of the agent who produced the content
            round_num: Current debate round

        Returns:
            StructuralAnalysisResult with detected fallacies, premise chains, etc.
        """
        if not content or len(content) < 20:
            return StructuralAnalysisResult()

        result = StructuralAnalysisResult()

        # Detect logical fallacies
        result.fallacies = self._detect_fallacies(content, agent, round_num)

        # Analyze premise chains
        result.premise_chains = self._extract_premise_chains(content, agent)

        # Identify unsupported claims
        result.unsupported_claims = self._find_unsupported_claims(content)

        # Detect contradictions within the content
        result.contradictions = self._detect_contradictions(content)

        # Track claim relationships across messages
        result.claim_relationships = self._extract_claim_relationships(content, agent)

        # Calculate overall structural confidence
        scores: list[float] = []
        if result.fallacies:
            scores.extend(f.confidence for f in result.fallacies)
        if result.premise_chains:
            scores.extend(p.confidence for p in result.premise_chains)
        if result.claim_relationships:
            scores.extend(r.confidence for r in result.claim_relationships)
        result.confidence = max(scores) if scores else 0.0

        # Store for cross-message analysis
        self._record_claims(content, agent, round_num)
        self._all_results.append(result)

        return result

    def _detect_fallacies(self, content: str, agent: str, round_num: int) -> list[FallacyDetection]:
        """Detect logical fallacies using keyword and pattern matching."""
        content_lower = content.lower()
        detected: list[FallacyDetection] = []

        for fallacy_type, indicators in self.FALLACY_INDICATORS.items():
            score = 0.0

            # Check keywords
            keywords = indicators.get("keywords", [])
            keyword_matches = sum(1 for kw in keywords if kw in content_lower)
            if keywords and keyword_matches:
                score += min(0.5, keyword_matches * 0.2)

            # Check regex patterns
            matched_excerpt = ""
            for regex in indicators.get("patterns", []):
                try:
                    match = re.search(regex, content_lower)
                    if match:
                        score += 0.35
                        if not matched_excerpt:
                            # Extract surrounding context for excerpt
                            start = max(0, match.start() - 20)
                            end = min(len(content), match.end() + 50)
                            matched_excerpt = content[start:end].strip()
                except re.error as e:
                    logger.debug("Invalid fallacy regex '%s': %s", regex, e)

            confidence = min(1.0, score)
            if confidence >= 0.3:
                excerpt = matched_excerpt or self._find_fallacy_excerpt(content, fallacy_type)
                detected.append(
                    FallacyDetection(
                        fallacy_type=fallacy_type,
                        confidence=confidence,
                        excerpt=excerpt[:150],
                        explanation=indicators.get("explanation", ""),
                        agent=agent,
                        round_num=round_num,
                    )
                )

        return detected

    def _find_fallacy_excerpt(self, content: str, fallacy_type: FallacyType) -> str:
        """Find an excerpt relevant to a fallacy detection."""
        indicators = self.FALLACY_INDICATORS.get(fallacy_type, {})
        sentences = re.split(r"[.!?]+", content)

        for sentence in sentences:
            sentence_lower = sentence.lower()
            for kw in indicators.get("keywords", []):
                if kw in sentence_lower:
                    return sentence.strip()[:150]

        return sentences[0].strip()[:150] if sentences else content[:100]

    def _extract_premise_chains(self, content: str, agent: str) -> list[PremiseChain]:
        """Extract premise-conclusion chains from content."""
        chains: list[PremiseChain] = []
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 10]

        if len(sentences) < 2:
            return chains

        # Look for conclusion markers with preceding premises
        for i, sentence in enumerate(sentences):
            conclusion_match = self._CONCLUSION_MARKERS.search(sentence)
            if conclusion_match:
                # Gather preceding sentences as premises
                premises = []
                for j in range(max(0, i - 3), i):
                    premises.append(sentences[j][:200])

                if premises:
                    # Check for gaps: premises with no causal connectors
                    has_gap = not any(self._PREMISE_MARKERS.search(p) for p in premises)
                    chains.append(
                        PremiseChain(
                            premises=premises,
                            conclusion=sentence[:200],
                            agent=agent,
                            confidence=0.6 if not has_gap else 0.4,
                            has_gap=has_gap,
                        )
                    )

        # Also look for "because" chains (premise follows conclusion)
        for i, sentence in enumerate(sentences):
            premise_match = self._PREMISE_MARKERS.search(sentence)
            if premise_match and i > 0:
                # Previous sentence is the claim, this sentence is the premise
                conclusion = sentences[i - 1][:200]
                # Check if this wasn't already captured
                already_captured = any(conclusion in c.conclusion for c in chains)
                if not already_captured:
                    chains.append(
                        PremiseChain(
                            premises=[sentence[:200]],
                            conclusion=conclusion,
                            agent=agent,
                            confidence=0.5,
                            has_gap=False,
                        )
                    )

        return chains

    def _find_unsupported_claims(self, content: str) -> list[str]:
        """Identify claims that lack supporting premises or evidence."""
        unsupported: list[str] = []
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 15]

        # Strong assertion markers without evidence
        assertion_pattern = re.compile(
            r"\b(must|definitely|certainly|clearly|obviously|undoubtedly|"
            r"without question|there is no doubt)\b",
            re.I,
        )
        evidence_pattern = re.compile(
            r"\b(because|since|given|evidence|data|research|study|"
            r"according to|for example|such as|shown by)\b",
            re.I,
        )

        for i, sentence in enumerate(sentences):
            if assertion_pattern.search(sentence):
                # Check if the sentence itself or neighboring sentences provide support
                has_evidence = evidence_pattern.search(sentence)
                if not has_evidence:
                    # Check adjacent sentences
                    prev_has = i > 0 and evidence_pattern.search(sentences[i - 1])
                    next_has = i < len(sentences) - 1 and evidence_pattern.search(sentences[i + 1])
                    if not prev_has and not next_has:
                        unsupported.append(sentence[:200])

        return unsupported

    def _detect_contradictions(self, content: str) -> list[tuple[str, str]]:
        """Detect internal contradictions within content."""
        contradictions: list[tuple[str, str]] = []
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 10]

        # Look for explicit contradiction markers
        negation_pairs = [
            (r"\bshould\b", r"\bshould not\b"),
            (r"\bmust\b", r"\bmust not\b"),
            (r"\bis (good|beneficial|positive)\b", r"\bis (bad|harmful|negative)\b"),
            (r"\bwe need\b", r"\bwe (don't|do not) need\b"),
            (r"\bcan\b", r"\bcannot\b"),
            (r"\bwill work\b", r"\bwill (not|never) work\b"),
            (r"\beffective\b", r"\bineffective\b"),
            (r"\bpossible\b", r"\bimpossible\b"),
        ]

        for i, sent_a in enumerate(sentences):
            for j, sent_b in enumerate(sentences):
                if j <= i:
                    continue
                sent_a_lower = sent_a.lower()
                sent_b_lower = sent_b.lower()
                for pos_pattern, neg_pattern in negation_pairs:
                    try:
                        if re.search(pos_pattern, sent_a_lower) and re.search(
                            neg_pattern, sent_b_lower
                        ):
                            contradictions.append((sent_a[:150], sent_b[:150]))
                        elif re.search(neg_pattern, sent_a_lower) and re.search(
                            pos_pattern, sent_b_lower
                        ):
                            contradictions.append((sent_a[:150], sent_b[:150]))
                    except re.error:
                        continue

        return contradictions

    def _extract_claim_relationships(self, content: str, agent: str) -> list[ClaimRelationship]:
        """Extract relationships between claims in the content and prior claims."""
        relationships: list[ClaimRelationship] = []
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 10]

        for sentence in sentences:
            # Check for support relationships
            if self._SUPPORT_MARKERS.search(sentence):
                # Find what is being supported (look in claim history)
                for prior in self._claim_history[-20:]:
                    prior_text = prior.get("text", "")
                    # Simple word overlap heuristic
                    overlap = self._word_overlap(sentence, prior_text)
                    if overlap >= 0.15:
                        relationships.append(
                            ClaimRelationship(
                                source_claim=sentence[:150],
                                target_claim=prior_text[:150],
                                relation="supports",
                                confidence=min(0.8, 0.4 + overlap),
                                agent=agent,
                            )
                        )
                        break

            # Check for contradiction relationships
            if self._CONTRADICTION_MARKERS.search(sentence):
                for prior in self._claim_history[-20:]:
                    prior_text = prior.get("text", "")
                    overlap = self._word_overlap(sentence, prior_text)
                    if overlap >= 0.1:
                        relationships.append(
                            ClaimRelationship(
                                source_claim=sentence[:150],
                                target_claim=prior_text[:150],
                                relation="contradicts",
                                confidence=min(0.8, 0.4 + overlap),
                                agent=agent,
                            )
                        )
                        break

            # Check for refinement relationships
            if self._REFINEMENT_MARKERS.search(sentence):
                for prior in self._claim_history[-20:]:
                    prior_text = prior.get("text", "")
                    overlap = self._word_overlap(sentence, prior_text)
                    if overlap >= 0.1:
                        relationships.append(
                            ClaimRelationship(
                                source_claim=sentence[:150],
                                target_claim=prior_text[:150],
                                relation="refines",
                                confidence=min(0.8, 0.4 + overlap),
                                agent=agent,
                            )
                        )
                        break

        return relationships

    def _word_overlap(self, text_a: str, text_b: str) -> float:
        """Calculate word overlap ratio between two texts."""
        words_a = {w.lower() for w in re.split(r"\W+", text_a) if len(w) >= 3}
        words_b = {w.lower() for w in re.split(r"\W+", text_b) if len(w) >= 3}
        if not words_a or not words_b:
            return 0.0
        overlap = len(words_a & words_b)
        return overlap / min(len(words_a), len(words_b))

    def _record_claims(self, content: str, agent: str, round_num: int) -> None:
        """Record claims from content for cross-message relationship tracking."""
        sentences = re.split(r"[.!?]+", content)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) >= 15:
                self._claim_history.append(
                    {
                        "text": sentence[:200],
                        "agent": agent,
                        "round_num": round_num,
                    }
                )

    def get_all_fallacies(self) -> list[FallacyDetection]:
        """Get all fallacies detected across all analyzed content."""
        fallacies: list[FallacyDetection] = []
        for result in self._all_results:
            fallacies.extend(result.fallacies)
        return fallacies

    def get_fallacy_summary(self) -> dict[str, int]:
        """Get counts of each fallacy type detected."""
        counts: dict[str, int] = {}
        for fallacy in self.get_all_fallacies():
            key = fallacy.fallacy_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def reset(self) -> None:
        """Reset all analysis state."""
        self._claim_history.clear()
        self._all_results.clear()


class RhetoricalAnalysisObserver:
    """
    Passive observer that detects rhetorical patterns in debates.

    Analyzes agent contributions without interfering with debate flow,
    generating audience-friendly commentary on debate dynamics.

    Optionally includes structural analysis for fallacy detection,
    premise chain identification, and claim relationship tracking
    when ``structural_analyzer`` is provided.

    Usage:
        observer = RhetoricalAnalysisObserver()

        # Observe a message
        observations = observer.observe(
            agent="claude",
            content="I agree with the point about security, but...",
            round_num=2
        )

        for obs in observations:
            print(f"{obs.pattern.value}: {obs.audience_commentary}")

        # Get debate dynamics summary
        dynamics = observer.get_debate_dynamics()

        # With structural analysis
        observer = RhetoricalAnalysisObserver(
            structural_analyzer=StructuralAnalyzer()
        )
        observations = observer.observe(agent="claude", content="...", round_num=1)
        structural = observer.get_structural_results()
    """

    # Pattern detection indicators
    PATTERN_INDICATORS = {
        RhetoricalPattern.CONCESSION: {
            "keywords": [
                "acknowledge",
                "fair point",
                "you're right",
                "i agree",
                "valid point",
                "granted",
                "i concede",
                "admittedly",
                "while true",
                "that said",
                "indeed",
            ],
            "patterns": [
                r"\bi (must )?(acknowledge|admit|concede)\b",
                r"\b(fair|valid|good) point\b",
                r"\byou('re| are) (right|correct)\b",
            ],
            "commentary": [
                "{agent} shows intellectual humility, acknowledging a valid point",
                "A moment of agreement! {agent} accepts the opposing view here",
                "{agent} concedes the point - building bridges in the debate",
            ],
        },
        RhetoricalPattern.REBUTTAL: {
            "keywords": [
                "however",
                "but",
                "on the contrary",
                "disagree",
                "actually",
                "in fact",
                "not quite",
                "that's not",
                "i would argue",
                "counter to",
                "misses",
            ],
            "patterns": [
                r"\b(however|but),?\s",
                r"\bi (would )?(disagree|argue)\b",
                r"\b(actually|in fact),?\s",
                r"\bon the contrary\b",
            ],
            "commentary": [
                "{agent} pushes back! The intellectual sparring intensifies",
                "Disagreement alert! {agent} challenges the prevailing view",
                "{agent} offers a compelling counterpoint",
            ],
        },
        RhetoricalPattern.SYNTHESIS: {
            "keywords": [
                "combining",
                "both perspectives",
                "integrate",
                "bringing together",
                "middle ground",
                "reconcile",
                "common ground",
                "bridge",
                "synthesis",
                "merge",
            ],
            "patterns": [
                r"\b(combin|integrat|reconcil|merg)(e|ing)\b",
                r"\b(both|all) (perspectives?|views?|points?)\b",
                r"\b(middle|common) ground\b",
            ],
            "commentary": [
                "{agent} attempts synthesis - weaving ideas together!",
                "Building consensus: {agent} finds common ground",
                "{agent} bridges the gap between opposing views",
            ],
        },
        RhetoricalPattern.APPEAL_TO_AUTHORITY: {
            "keywords": [
                "according to",
                "research shows",
                "experts say",
                "studies indicate",
                "as per",
                "documentation states",
                "best practices",
                "industry standard",
            ],
            "patterns": [
                r"\baccording to\b",
                r"\b(research|studies|experts?) (show|indicate|say|suggest)\b",
                r"\bbest practices?\b",
            ],
            "commentary": [
                "{agent} brings authoritative sources to the table",
                "Invoking expertise: {agent} appeals to established knowledge",
                "{agent} grounds the argument in research",
            ],
        },
        RhetoricalPattern.APPEAL_TO_EVIDENCE: {
            "keywords": [
                "for example",
                "such as",
                "specifically",
                "consider the case",
                "evidence suggests",
                "data shows",
                "looking at",
                "we can see",
                "demonstrated by",
            ],
            "patterns": [
                r"\bfor (example|instance)\b",
                r"\b(such as|specifically|e\.g\.)\b",
                r"\b(evidence|data) (shows|suggests|indicates)\b",
            ],
            "commentary": [
                "{agent} backs up claims with concrete evidence",
                "Getting specific: {agent} presents examples",
                "{agent} strengthens the argument with evidence",
            ],
        },
        RhetoricalPattern.TECHNICAL_DEPTH: {
            "keywords": [
                "implementation",
                "architecture",
                "algorithm",
                "complexity",
                "performance",
                "scalability",
                "database",
                "api",
                "protocol",
                "async",
                "threading",
            ],
            "patterns": [
                r"\bO\([n\d\s\*log]+\)\b",  # Big O notation
                r"\b(implement|architect|design)(?:ed|ing|ure)?\b",
                r"\b(async|await|threading|concurrent)\b",
            ],
            "commentary": [
                "{agent} dives into technical details",
                "Technical depth: {agent} gets into the nitty-gritty",
                "{agent} brings engineering precision to the debate",
            ],
        },
        RhetoricalPattern.RHETORICAL_QUESTION: {
            "keywords": [],
            "patterns": [
                r"\b(what if|why would|how can|isn't it|shouldn't we)\b[^?]*\?",
                r"\?\s*(right|no|isn't it)\??\s*$",
            ],
            "commentary": [
                "{agent} poses a thought-provoking question",
                "Rhetorical flourish: {agent} challenges the audience to think",
                "{agent} uses questions to make their point",
            ],
        },
        RhetoricalPattern.ANALOGY: {
            "keywords": [
                "like",
                "similar to",
                "just as",
                "analogous",
                "think of it as",
                "imagine",
                "metaphorically",
                "in the same way",
                "comparable to",
            ],
            "patterns": [
                r"\b(just )?like\s+(a|the|when)\b",
                r"\bsimilar to\b",
                r"\bjust as\b[^.]+so\b",
                r"\bthink of it (like|as)\b",
            ],
            "commentary": [
                "{agent} draws an illuminating analogy",
                "Making it relatable: {agent} uses comparison to clarify",
                "{agent} bridges concepts with an apt metaphor",
            ],
        },
        RhetoricalPattern.QUALIFICATION: {
            "keywords": [
                "depends on",
                "in some cases",
                "typically",
                "usually",
                "often",
                "sometimes",
                "it varies",
                "context-dependent",
                "nuanced",
            ],
            "patterns": [
                r"\b(depends on|in some cases)\b",
                r"\b(typically|usually|often|sometimes)\b",
                r"\bit('s| is) (nuanced|complex|complicated)\b",
            ],
            "commentary": [
                "{agent} adds important nuance to the discussion",
                "Qualification spotted: {agent} acknowledges complexity",
                "{agent} reminds us that context matters",
            ],
        },
    }

    def __init__(
        self,
        broadcast_callback: Callable[[dict], Any] | None = None,
        min_confidence: float = 0.5,
        structural_analyzer: StructuralAnalyzer | None = None,
    ):
        """
        Initialize the observer.

        Args:
            broadcast_callback: Optional callback for streaming observations
            min_confidence: Minimum confidence for reporting observations
            structural_analyzer: Optional structural analyzer for fallacy
                detection, premise chain analysis, and claim relationship tracking
        """
        self.broadcast_callback = broadcast_callback
        self.min_confidence = min_confidence
        self.observations: list[RhetoricalObservation] = []
        self.agent_patterns: dict[str, dict[str, int]] = {}  # Track patterns per agent
        self.structural_analyzer = structural_analyzer
        self._structural_results: list[StructuralAnalysisResult] = []

    def observe(
        self,
        agent: str,
        content: str,
        round_num: int = 0,
    ) -> list[RhetoricalObservation]:
        """
        Analyze content for rhetorical patterns.

        Args:
            agent: Name of the agent
            content: Text content to analyze
            round_num: Current debate round

        Returns:
            List of detected patterns with commentary
        """
        if not content or len(content) < 20:
            return []

        detected = self._detect_patterns(content)

        # Run structural analysis if analyzer is configured
        structural_result: StructuralAnalysisResult | None = None
        if self.structural_analyzer is not None:
            try:
                structural_result = self.structural_analyzer.analyze(
                    content, agent=agent, round_num=round_num
                )
                self._structural_results.append(structural_result)
            except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
                logger.warning("structural_analysis_failed error=%s", e)

        observations = []

        for pattern, keyword_confidence in detected:
            # Combine keyword confidence with structural confidence
            # using max(keyword, structural) when both are available
            confidence = keyword_confidence
            if structural_result is not None and structural_result.confidence > 0:
                confidence = max(keyword_confidence, structural_result.confidence)

            if confidence < self.min_confidence:
                continue

            # Find excerpt
            excerpt = self._find_excerpt(content, pattern)

            # Generate commentary
            commentary = self._generate_commentary(agent, pattern)

            observation = RhetoricalObservation(
                pattern=pattern,
                agent=agent,
                round_num=round_num,
                confidence=confidence,
                excerpt=excerpt,
                audience_commentary=commentary,
            )

            observations.append(observation)
            self.observations.append(observation)

            # Track per-agent
            if agent not in self.agent_patterns:
                self.agent_patterns[agent] = {}
            pattern_key = pattern.value
            self.agent_patterns[agent][pattern_key] = (
                self.agent_patterns[agent].get(pattern_key, 0) + 1
            )

        # Broadcast if callback set
        if self.broadcast_callback and observations:
            try:
                self.broadcast_callback(
                    {
                        "type": "rhetorical_observations",
                        "data": {
                            "agent": agent,
                            "round_num": round_num,
                            "observations": [o.to_dict() for o in observations],
                        },
                    }
                )
            except (
                TypeError,
                ValueError,
                AttributeError,
                RuntimeError,
                OSError,
                ConnectionError,
            ) as e:
                logger.warning("rhetorical_broadcast_failed error=%s", e)

        return observations

    def _detect_patterns(self, content: str) -> list[tuple[RhetoricalPattern, float]]:
        """Detect rhetorical patterns in content."""
        content_lower = content.lower()
        detected = []

        for pattern, indicators in self.PATTERN_INDICATORS.items():
            score = 0.0

            # Check keywords
            keywords = indicators.get("keywords", [])
            keyword_matches = sum(1 for kw in keywords if kw in content_lower)
            if keywords and keyword_matches:
                score += min(0.5, keyword_matches * 0.15)

            # Check regex patterns
            regex_patterns = indicators.get("patterns", [])
            for regex in regex_patterns:
                try:
                    if re.search(regex, content_lower):
                        score += 0.3
                except re.error as e:
                    logger.debug("Invalid regex pattern '%s': %s", regex, e)

            # Normalize score
            confidence = min(1.0, score)

            if confidence >= self.min_confidence:
                detected.append((pattern, confidence))

        return detected

    def _find_excerpt(self, content: str, pattern: RhetoricalPattern) -> str:
        """Find a relevant excerpt for the pattern."""
        indicators = self.PATTERN_INDICATORS.get(pattern, {})
        # Try to find a sentence containing pattern indicators
        sentences = re.split(r"[.!?]+", content)

        for sentence in sentences:
            sentence_lower = sentence.lower()

            # Check keywords
            for kw in indicators.get("keywords", []):
                if kw in sentence_lower:
                    return sentence.strip()[:150]

            # Check patterns
            for regex in indicators.get("patterns", []):
                try:
                    if re.search(regex, sentence_lower):
                        return sentence.strip()[:150]
                except re.error as e:
                    logger.debug("Invalid regex pattern '%s': %s", regex, e)

        # Fallback to first sentence
        if sentences:
            return sentences[0].strip()[:150]

        return content[:100]

    def _generate_commentary(self, agent: str, pattern: RhetoricalPattern) -> str:
        """Generate audience commentary for a pattern."""
        indicators = self.PATTERN_INDICATORS.get(pattern, {})
        templates = indicators.get("commentary", [])

        if templates:
            import random

            template = random.choice(templates)
            return template.format(agent=agent)

        return f"{agent} employs {pattern.value} in their argument"

    def get_debate_dynamics(self) -> dict:
        """Get summary of overall debate dynamics."""
        if not self.observations:
            return {
                "total_observations": 0,
                "patterns_detected": {},
                "agent_styles": {},
                "dominant_pattern": None,
            }

        # Count patterns
        pattern_counts: dict[str, int] = {}
        for obs in self.observations:
            key = obs.pattern.value
            pattern_counts[key] = pattern_counts.get(key, 0) + 1

        # Determine dominant pattern
        dominant = max(pattern_counts.items(), key=lambda x: x[1])[0] if pattern_counts else None

        # Characterize agent styles
        agent_styles = {}
        for agent, patterns in self.agent_patterns.items():
            if patterns:
                top_pattern = max(patterns.items(), key=lambda x: x[1])[0]
                style = self._pattern_to_style(top_pattern)
                agent_styles[agent] = {
                    "dominant_pattern": top_pattern,
                    "style": style,
                    "pattern_diversity": len(patterns),
                }

        return {
            "total_observations": len(self.observations),
            "patterns_detected": pattern_counts,
            "agent_styles": agent_styles,
            "dominant_pattern": dominant,
            "debate_character": self._characterize_debate(pattern_counts),
        }

    def _pattern_to_style(self, pattern: str) -> str:
        """Map pattern to debate style label."""
        style_map = {
            "concession": "diplomatic",
            "rebuttal": "combative",
            "synthesis": "collaborative",
            "appeal_to_authority": "scholarly",
            "appeal_to_evidence": "empirical",
            "technical_depth": "technical",
            "rhetorical_question": "socratic",
            "analogy": "illustrative",
            "qualification": "nuanced",
        }
        return style_map.get(pattern, "balanced")

    def _characterize_debate(self, pattern_counts: dict) -> str:
        """Characterize overall debate based on pattern distribution."""
        if not pattern_counts:
            return "emerging"

        total = sum(pattern_counts.values())

        # Check for consensus-building (concession + synthesis)
        collaborative = pattern_counts.get("concession", 0) + pattern_counts.get("synthesis", 0)
        if collaborative > total * 0.4:
            return "collaborative"

        # Check for combative (high rebuttal)
        if pattern_counts.get("rebuttal", 0) > total * 0.4:
            return "contentious"

        # Check for technical (high technical depth)
        if pattern_counts.get("technical_depth", 0) > total * 0.3:
            return "technical"

        # Check for evidence-heavy
        evidence = pattern_counts.get("appeal_to_evidence", 0) + pattern_counts.get(
            "appeal_to_authority", 0
        )
        if evidence > total * 0.3:
            return "evidence-driven"

        return "balanced"

    def get_recent_observations(self, limit: int = 10) -> list[dict]:
        """Get recent observations."""
        return [o.to_dict() for o in self.observations[-limit:]]

    def get_structural_results(self) -> list[StructuralAnalysisResult]:
        """Get all structural analysis results collected during observation."""
        return list(self._structural_results)

    def reset(self) -> None:
        """Reset all observations."""
        self.observations = []
        self.agent_patterns = {}
        self._structural_results = []
        if self.structural_analyzer is not None:
            self.structural_analyzer.reset()


# Global observer instance
_observer: RhetoricalAnalysisObserver | None = None


def get_rhetorical_observer() -> RhetoricalAnalysisObserver:
    """Get the global rhetorical observer instance."""
    global _observer
    if _observer is None:
        _observer = RhetoricalAnalysisObserver()
    return _observer


def reset_rhetorical_observer() -> None:
    """Reset the global observer (for testing)."""
    global _observer
    _observer = None
