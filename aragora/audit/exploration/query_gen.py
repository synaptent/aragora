"""Query generator for follow-up questions during exploration.

Generates intelligent follow-up questions based on:
- Current understanding gaps
- Unresolved references
- Contradictions found
- Exploration objective
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aragora.audit.exploration.session import (
    ChunkUnderstanding,
    Question,
    Insight,
)
from aragora.audit.exploration.agents import ExplorationAgent

logger = logging.getLogger(__name__)


class QuestionType:
    """Types of follow-up questions."""

    CLARIFICATION = "clarification"  # What does X mean in this context?
    EVIDENCE = "evidence"  # What supports the claim that Y?
    CONTRADICTION = "contradiction"  # How do we reconcile A with B?
    REFERENCE = "reference"  # Where is Z defined/explained?
    IMPLICATION = "implication"  # What are the consequences of W?
    DEFINITION = "definition"  # How is term T defined?
    SCOPE = "scope"  # What are the boundaries of X?
    TEMPORAL = "temporal"  # When did X occur/change?


@dataclass
class UnderstandingGap:
    """Represents a gap in current understanding."""

    description: str
    gap_type: str  # missing_info, unclear, contradictory
    related_chunks: list[str] = field(default_factory=list)
    priority: float = 0.5


class QueryGenerator:
    """Generates follow-up questions based on understanding gaps.

    Uses pattern-based generation and optional agent assistance
    to produce targeted questions that drive exploration forward.
    """

    # Question templates by type
    TEMPLATES = {
        QuestionType.CLARIFICATION: [
            "What exactly is meant by '{term}' in the context of {context}?",
            "Can you clarify the meaning of '{term}'?",
            "How should '{term}' be interpreted here?",
        ],
        QuestionType.EVIDENCE: [
            "What evidence supports the claim that {claim}?",
            "How can we verify that {claim}?",
            "What sources confirm {claim}?",
        ],
        QuestionType.CONTRADICTION: [
            "How do we reconcile '{statement1}' with '{statement2}'?",
            "Why does {source1} say '{statement1}' while {source2} says '{statement2}'?",
            "Which is correct: '{statement1}' or '{statement2}'?",
        ],
        QuestionType.REFERENCE: [
            "Where is '{reference}' defined or explained?",
            "What document contains details about '{reference}'?",
            "Can you locate the source for '{reference}'?",
        ],
        QuestionType.IMPLICATION: [
            "What are the implications of {fact}?",
            "What consequences follow from {fact}?",
            "How does {fact} affect {context}?",
        ],
        QuestionType.DEFINITION: [
            "How is '{term}' defined in this document?",
            "What is the official definition of '{term}'?",
        ],
        QuestionType.SCOPE: [
            "What are the boundaries of {concept}?",
            "What is included/excluded from {concept}?",
        ],
        QuestionType.TEMPORAL: [
            "When was {event} established/changed?",
            "What is the timeline for {event}?",
        ],
    }

    def __init__(
        self,
        agent: ExplorationAgent | None = None,
        max_questions_per_gap: int = 2,
        dedup_threshold: float = 0.8,
    ):
        """Initialize the query generator.

        Args:
            agent: Optional agent for AI-assisted question generation
            max_questions_per_gap: Maximum questions to generate per gap
            dedup_threshold: Similarity threshold for deduplication (0-1)
        """
        self.agent = agent
        self.max_questions_per_gap = max_questions_per_gap
        self.dedup_threshold = dedup_threshold
        self._asked_questions: set[str] = set()

    def identify_gaps(
        self,
        understandings: list[ChunkUnderstanding],
        insights: list[Insight],
        objective: str,
    ) -> list[UnderstandingGap]:
        """Identify gaps in current understanding.

        Args:
            understandings: Current chunk understandings
            insights: Current insights
            objective: Exploration objective

        Returns:
            List of identified understanding gaps
        """
        gaps = []

        # Identify low-confidence areas
        for understanding in understandings:
            if understanding.confidence < 0.5:
                gaps.append(
                    UnderstandingGap(
                        description=f"Low confidence in understanding of {understanding.chunk_id}",
                        gap_type="unclear",
                        related_chunks=[understanding.chunk_id],
                        priority=1.0 - understanding.confidence,
                    )
                )

            # Check for raised questions
            for question in understanding.questions_raised:
                gaps.append(
                    UnderstandingGap(
                        description=question,
                        gap_type="missing_info",
                        related_chunks=[understanding.chunk_id],
                        priority=0.6,
                    )
                )

        # Identify contradictions between insights
        for i, insight1 in enumerate(insights):
            for insight2 in insights[i + 1 :]:
                if self._might_contradict(insight1, insight2):
                    gaps.append(
                        UnderstandingGap(
                            description=f"Potential contradiction: '{insight1.title}' vs '{insight2.title}'",
                            gap_type="contradictory",
                            related_chunks=insight1.evidence_chunks + insight2.evidence_chunks,
                            priority=0.9,
                        )
                    )

        # Identify unverified high-importance insights
        for insight in insights:
            if insight.confidence < 0.7 and not insight.verified_by:
                gaps.append(
                    UnderstandingGap(
                        description=f"Unverified: {insight.title}",
                        gap_type="missing_info",
                        related_chunks=insight.evidence_chunks,
                        priority=0.7,
                    )
                )

        return sorted(gaps, key=lambda g: g.priority, reverse=True)

    def _might_contradict(self, insight1: Insight, insight2: Insight) -> bool:
        """Check if two insights might contradict each other."""
        # Simple heuristic: check for opposing keywords
        opposing_pairs = [
            ("increase", "decrease"),
            ("allow", "prohibit"),
            ("required", "optional"),
            ("always", "never"),
            ("before", "after"),
            ("true", "false"),
            ("yes", "no"),
        ]

        text1 = f"{insight1.title} {insight1.description}".lower()
        text2 = f"{insight2.title} {insight2.description}".lower()

        for word1, word2 in opposing_pairs:
            if (word1 in text1 and word2 in text2) or (word2 in text1 and word1 in text2):
                # Also check for topic overlap
                words1 = set(text1.split())
                words2 = set(text2.split())
                overlap = len(words1 & words2)
                if overlap >= 3:  # Some topic overlap
                    return True

        return False

    async def generate_questions(
        self,
        gaps: list[UnderstandingGap],
        objective: str,
        asked_questions: list[Question] | None = None,
    ) -> list[Question]:
        """Generate questions to fill understanding gaps.

        Args:
            gaps: Identified understanding gaps
            objective: Exploration objective
            asked_questions: Questions already asked

        Returns:
            List of new questions
        """
        # Update asked questions set
        if asked_questions:
            for q in asked_questions:
                self._asked_questions.add(self._normalize_question(q.text))

        questions = []

        for gap in gaps[:5]:  # Process top 5 gaps
            gap_questions = self._generate_for_gap(gap, objective)

            for q in gap_questions[: self.max_questions_per_gap]:
                # Dedup check
                if not self._is_duplicate(q.text):
                    questions.append(q)
                    self._asked_questions.add(self._normalize_question(q.text))

        # Sort by priority
        return sorted(questions, key=lambda q: q.priority, reverse=True)

    def _generate_for_gap(self, gap: UnderstandingGap, objective: str) -> list[Question]:
        """Generate questions for a specific gap."""
        questions = []

        if gap.gap_type == "unclear":
            # Generate clarification questions
            for template in self.TEMPLATES[QuestionType.CLARIFICATION][:1]:
                # Extract key term from description
                term = self._extract_key_term(gap.description)
                if term:
                    q_text = template.format(term=term, context=objective)
                    questions.append(
                        Question(
                            text=q_text,
                            question_type=QuestionType.CLARIFICATION,
                            priority=gap.priority,
                            source_chunk=gap.related_chunks[0] if gap.related_chunks else "",
                        )
                    )

        elif gap.gap_type == "missing_info":
            # The gap description is often already a question
            if "?" in gap.description:
                questions.append(
                    Question(
                        text=gap.description,
                        question_type=QuestionType.EVIDENCE,
                        priority=gap.priority,
                        source_chunk=gap.related_chunks[0] if gap.related_chunks else "",
                    )
                )
            else:
                # Generate evidence question
                for template in self.TEMPLATES[QuestionType.EVIDENCE][:1]:
                    q_text = template.format(claim=gap.description)
                    questions.append(
                        Question(
                            text=q_text,
                            question_type=QuestionType.EVIDENCE,
                            priority=gap.priority,
                            source_chunk=gap.related_chunks[0] if gap.related_chunks else "",
                        )
                    )

        elif gap.gap_type == "contradictory":
            # Generate contradiction resolution question
            questions.append(
                Question(
                    text=gap.description.replace(
                        "Potential contradiction: ", "How do we reconcile "
                    ),
                    question_type=QuestionType.CONTRADICTION,
                    priority=gap.priority,
                    source_chunk=gap.related_chunks[0] if gap.related_chunks else "",
                )
            )

        return questions

    def _extract_key_term(self, text: str) -> str | None:
        """Extract a key term from text for question generation."""
        # Simple heuristic: look for quoted terms or capitalized phrases
        import re

        # Look for quoted terms
        quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", text)
        if quoted:
            return quoted[0][0] or quoted[0][1]

        # Look for capitalized multi-word terms
        caps = re.findall(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text)
        if caps:
            return caps[0]

        # Return first noun-like word
        words = text.split()
        for word in words:
            if len(word) > 3 and word[0].isupper():
                return word

        return None

    def _normalize_question(self, text: str) -> str:
        """Normalize question text for deduplication."""
        # Remove punctuation and lowercase
        import re

        normalized = re.sub(r"[^\w\s]", "", text.lower())
        # Remove common words
        stop_words = {"what", "how", "why", "when", "where", "is", "are", "the", "a", "an"}
        words = [w for w in normalized.split() if w not in stop_words]
        return " ".join(sorted(words))

    def _is_duplicate(self, text: str) -> bool:
        """Check if a question is a duplicate of one already asked."""
        normalized = self._normalize_question(text)

        for asked in self._asked_questions:
            # Simple word overlap check
            words1 = set(normalized.split())
            words2 = set(asked.split())
            if not words1 or not words2:
                continue
            overlap = len(words1 & words2) / max(len(words1), len(words2))
            if overlap >= self.dedup_threshold:
                return True

        return False

    def prioritize_questions(
        self,
        questions: list[Question],
        objective: str,
        recent_insights: list[Insight] | None = None,
    ) -> list[Question]:
        """Prioritize questions based on objective relevance.

        Args:
            questions: Questions to prioritize
            objective: Exploration objective
            recent_insights: Recent insights for context

        Returns:
            Prioritized list of questions
        """
        objective_words = set(objective.lower().split())

        for question in questions:
            # Boost priority for objective-relevant questions
            question_words = set(question.text.lower().split())
            relevance = len(objective_words & question_words) / max(len(objective_words), 1)
            question.priority = question.priority * (1 + relevance * 0.5)

            # Boost contradictions (they're usually important)
            if question.question_type == QuestionType.CONTRADICTION:
                question.priority *= 1.2

        return sorted(questions, key=lambda q: q.priority, reverse=True)
