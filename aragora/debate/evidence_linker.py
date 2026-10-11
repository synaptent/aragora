"""
Evidence-Claim Linker for semantic evidence validation.

This module provides semantic linking between claims and their supporting evidence,
going beyond simple pattern matching to assess whether evidence actually supports
the claims being made.

Key capabilities:
- Extract assertion claims from text
- Find evidence markers and their types
- Compute semantic link strength between claims and evidence
- Calculate overall evidence coverage for proposals

Works with optional sentence-transformers for semantic similarity, with fallback
to heuristic matching when unavailable.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

from aragora.debate.evidence_quality import (
    EvidenceMarker,
    EvidenceQualityAnalyzer,
    EvidenceType,
)
from aragora.utils.env import is_offline_mode, is_truthy_env

logger = logging.getLogger(__name__)

# Lazy availability check for sentence-transformers.
# We avoid importing the actual module at file scope because it transitively
# imports ``transformers`` -> ``huggingface_hub``, which may attempt network
# downloads (model cache validation, token checks) at import time.  This
# blocks indefinitely in offline / CI environments.
_EMBEDDINGS_CHECKED = False
_EMBEDDINGS_AVAILABLE: bool = False
_SentenceTransformer: type | None = None
_np = None  # numpy module, lazily loaded


def _ensure_embeddings_checked() -> None:
    """Lazily probe for sentence-transformers + numpy on first use."""
    global _EMBEDDINGS_CHECKED, _EMBEDDINGS_AVAILABLE, _SentenceTransformer, _np
    if _EMBEDDINGS_CHECKED:
        return
    _EMBEDDINGS_CHECKED = True
    try:
        import numpy as __np
        from sentence_transformers import (
            SentenceTransformer as __ST,
        )

        _SentenceTransformer = __ST
        _np = __np
        _EMBEDDINGS_AVAILABLE = True
    except (RuntimeError, ValueError, TypeError, OSError, ImportError) as e:
        logger.debug(
            "sentence-transformers not available: %s. Using heuristic claim-evidence linking", e
        )


# Keep the public name for backward compatibility (e.g. ``from
# aragora.debate.evidence_linker import EMBEDDINGS_AVAILABLE``).  Reads go
# through the module-level ``__getattr__`` so the lazy check runs first.


def __getattr__(name: str):
    if name == "EMBEDDINGS_AVAILABLE":
        _ensure_embeddings_checked()
        return _EMBEDDINGS_AVAILABLE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _prefer_local_embedding_files() -> bool:
    """Avoid network-backed model downloads in offline and pytest runs."""
    return (
        is_offline_mode()
        or is_truthy_env("HF_HUB_OFFLINE", default=False)
        or is_truthy_env("TRANSFORMERS_OFFLINE", default=False)
        or "PYTEST_CURRENT_TEST" in os.environ
    )


# Claim detection patterns
CLAIM_INDICATORS = [
    r"(?:is|are|was|were|will be|should be|must be|cannot be)\s+\w+",
    r"(?:we|they|it|this|the)\s+(?:should|must|need to|have to|ought to)",
    r"(?:therefore|thus|hence|consequently|as a result)",
    r"(?:I|we)\s+(?:believe|argue|propose|suggest|recommend|conclude)",
    r"(?:the|a|an)\s+\w+\s+(?:is|are|was|were)\s+(?:better|worse|faster|slower|more|less)",
    r"(?:this|that|it)\s+(?:causes|prevents|enables|leads to|results in)",
]

# Non-claim patterns (questions, hedges)
NON_CLAIM_PATTERNS = [
    r"^\s*(?:what|why|how|when|where|who|which)\s+",  # Questions
    r"^\s*(?:maybe|perhaps|possibly|potentially)",  # Strong hedges
    r"^\s*(?:I think|I guess|it seems|it appears)",  # Weak assertions
]


@dataclass
class EvidenceLink:
    """A link between a claim and its supporting evidence."""

    claim: str
    claim_start: int
    claim_end: int
    evidence: str
    evidence_type: EvidenceType
    evidence_position: int
    link_strength: float  # 0-1, how well evidence supports claim

    @property
    def is_strong_link(self) -> bool:
        """Whether this is a strong evidence-claim link."""
        return self.link_strength >= 0.6


@dataclass
class ClaimAnalysis:
    """Analysis of claims in a text."""

    claims: list[str] = field(default_factory=list)
    claim_positions: list[tuple[int, int]] = field(default_factory=list)  # (start, end)
    total_sentences: int = 0
    claim_density: float = 0.0  # Fraction of sentences that are claims


@dataclass
class EvidenceCoverageResult:
    """Result of evidence coverage analysis."""

    coverage: float  # Fraction of claims with supporting evidence
    total_claims: int
    linked_claims: int
    unlinked_claims: list[str]  # Claims without evidence
    evidence_gaps: list[str]  # Specific gaps identified
    links: list[EvidenceLink] = field(default_factory=list)


class EvidenceClaimLinker:
    """
    Links evidence to claims for semantic validation.

    This class goes beyond pattern matching to assess whether evidence
    actually supports the claims being made, using either:
    - Semantic similarity (when sentence-transformers available)
    - Heuristic proximity and keyword matching (fallback)

    Usage:
        linker = EvidenceClaimLinker()

        # Extract claims from text
        claims = linker.extract_claims(response)

        # Link evidence to claims
        links = linker.link_evidence_to_claims(response)

        # Get overall coverage
        coverage = linker.compute_evidence_coverage(response)
        print(f"{coverage.coverage:.0%} of claims have evidence")
    """

    def __init__(
        self,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        use_embeddings: bool | None = None,
        min_link_strength: float = 0.5,
        proximity_window: int = 300,  # Characters to search for evidence
    ):
        """
        Initialize the linker.

        Args:
            embedding_model: Model for semantic similarity (if available)
            use_embeddings: Force embeddings on/off (None = auto-detect)
            min_link_strength: Minimum strength for valid link
            proximity_window: Characters to search around claim for evidence
        """
        self.min_link_strength = min_link_strength
        self.proximity_window = proximity_window

        # Compile patterns
        self._claim_patterns = [re.compile(p, re.IGNORECASE) for p in CLAIM_INDICATORS]
        self._non_claim_patterns = [re.compile(p, re.IGNORECASE) for p in NON_CLAIM_PATTERNS]

        # Evidence analyzer for marker detection
        self._evidence_analyzer = EvidenceQualityAnalyzer()

        # Initialize embedder if available and requested
        self._embedder = None
        _ensure_embeddings_checked()
        if use_embeddings is True and not _EMBEDDINGS_AVAILABLE:
            logger.warning("Embeddings requested but sentence-transformers not installed")
        elif (
            use_embeddings is not False
            and _EMBEDDINGS_AVAILABLE
            and _SentenceTransformer is not None
        ):
            try:
                init_kwargs: dict[str, object] = {}
                if _prefer_local_embedding_files():
                    init_kwargs["local_files_only"] = True
                self._embedder = _SentenceTransformer(embedding_model, **init_kwargs)
                logger.debug("Loaded embedding model: %s", embedding_model)
            except Exception as e:  # noqa: BLE001 - embedder init must degrade gracefully
                logger.warning("Failed to load embedding model: %s", e)

    @property
    def uses_embeddings(self) -> bool:
        """Whether semantic embeddings are being used."""
        return self._embedder is not None

    def extract_claims(self, text: str) -> ClaimAnalysis:
        """
        Extract assertion claims from text.

        Claims are sentences that make factual or normative assertions,
        as opposed to questions, hedges, or meta-commentary.

        Args:
            text: The text to analyze

        Returns:
            ClaimAnalysis with extracted claims and positions
        """
        if not text:
            return ClaimAnalysis()

        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)
        claims = []
        claim_positions = []
        current_pos = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Find position in original text
            try:
                start = text.index(sentence, current_pos)
            except ValueError:
                start = current_pos
            end = start + len(sentence)
            current_pos = end

            # Check if this is a claim
            if self._is_claim(sentence):
                claims.append(sentence)
                claim_positions.append((start, end))

        total = len(sentences)
        claim_density = len(claims) / total if total > 0 else 0.0

        return ClaimAnalysis(
            claims=claims,
            claim_positions=claim_positions,
            total_sentences=total,
            claim_density=claim_density,
        )

    def _is_claim(self, sentence: str) -> bool:
        """Determine if a sentence is a claim."""
        # Must be substantive
        if len(sentence) < 20:
            return False

        # Check for non-claim patterns (questions, hedges)
        for pattern in self._non_claim_patterns:
            if pattern.search(sentence):
                return False

        # Check for claim indicators
        for pattern in self._claim_patterns:
            if pattern.search(sentence):
                return True

        # Fallback: longer sentences without question marks are likely claims
        if "?" not in sentence and len(sentence) > 50:
            return True

        return False

    def link_evidence_to_claims(self, text: str) -> list[EvidenceLink]:
        """
        Find evidence markers and link to nearest claims.

        Args:
            text: The text to analyze

        Returns:
            List of EvidenceLink objects
        """
        if not text:
            return []

        # Extract claims and evidence
        claim_analysis = self.extract_claims(text)
        evidence_markers = self._evidence_analyzer._detect_evidence(text)

        if not claim_analysis.claims or not evidence_markers:
            return []

        links = []

        for claim, (start, end) in zip(claim_analysis.claims, claim_analysis.claim_positions):
            # Find evidence near this claim
            best_evidence = self._find_supporting_evidence(
                claim, start, end, evidence_markers, text
            )
            if best_evidence:
                links.append(best_evidence)

        return links

    def _find_supporting_evidence(
        self,
        claim: str,
        claim_start: int,
        claim_end: int,
        evidence_markers: list[EvidenceMarker],
        full_text: str,
    ) -> EvidenceLink | None:
        """Find the best supporting evidence for a claim."""
        best_link = None
        best_strength = 0.0

        for marker in evidence_markers:
            # Check proximity
            distance = min(
                abs(marker.position - claim_start),
                abs(marker.position - claim_end),
            )

            if distance > self.proximity_window:
                continue

            # Compute link strength
            strength = self._compute_link_strength(claim, marker, distance)

            if strength > best_strength:
                best_strength = strength
                best_link = EvidenceLink(
                    claim=claim,
                    claim_start=claim_start,
                    claim_end=claim_end,
                    evidence=marker.text,
                    evidence_type=marker.evidence_type,
                    evidence_position=marker.position,
                    link_strength=strength,
                )

        return best_link

    def _compute_link_strength(
        self,
        claim: str,
        evidence: EvidenceMarker,
        distance: int,
    ) -> float:
        """
        Compute how strongly evidence supports a claim.

        Uses semantic similarity if available, otherwise heuristic matching.
        """
        # Base score from proximity
        proximity_score = max(0.0, 1.0 - distance / self.proximity_window)

        # Evidence type quality boost
        type_boost = {
            EvidenceType.CITATION: 0.3,
            EvidenceType.DATA: 0.25,
            EvidenceType.TOOL_OUTPUT: 0.25,
            EvidenceType.EXAMPLE: 0.2,
            EvidenceType.QUOTE: 0.15,
            EvidenceType.REASONING: 0.1,
            EvidenceType.NONE: 0.0,
        }.get(evidence.evidence_type, 0.0)

        # Semantic similarity if available
        if self._embedder is not None:
            try:
                semantic_score = self._compute_semantic_similarity(claim, evidence.text)
            except (RuntimeError, ValueError, TypeError, OSError) as e:
                logger.debug("Semantic similarity failed: %s", e)
                semantic_score = 0.5
        else:
            # Heuristic keyword overlap
            semantic_score = self._compute_keyword_overlap(claim, evidence.text)

        # Combine scores
        strength = (
            0.3 * proximity_score
            + 0.3 * semantic_score
            + 0.2 * type_boost
            + 0.2 * evidence.confidence
        )

        return min(1.0, strength)

    def _compute_semantic_similarity(self, text1: str, text2: str) -> float:
        """Compute semantic similarity using embeddings."""
        if self._embedder is None or _np is None:
            return 0.5

        embeddings = self._embedder.encode([text1, text2])
        # Cosine similarity
        similarity = _np.dot(embeddings[0], embeddings[1]) / (
            _np.linalg.norm(embeddings[0]) * _np.linalg.norm(embeddings[1])
        )
        # Normalize to 0-1
        return float((similarity + 1) / 2)

    def _compute_keyword_overlap(self, claim: str, evidence: str) -> float:
        """Compute keyword overlap as fallback for semantic similarity."""
        # Extract keywords (alphanumeric tokens > 3 chars)
        claim_words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", claim))
        evidence_words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", evidence))

        if not claim_words or not evidence_words:
            return 0.3  # Neutral if no meaningful words

        # Jaccard-like overlap
        intersection = claim_words & evidence_words
        union = claim_words | evidence_words

        return len(intersection) / len(union) if union else 0.0

    def compute_evidence_coverage(self, text: str) -> EvidenceCoverageResult:
        """
        Compute overall evidence coverage for a text.

        Args:
            text: The text to analyze

        Returns:
            EvidenceCoverageResult with coverage metrics
        """
        if not text:
            return EvidenceCoverageResult(
                coverage=0.0,
                total_claims=0,
                linked_claims=0,
                unlinked_claims=[],
                evidence_gaps=[],
            )

        claim_analysis = self.extract_claims(text)
        links = self.link_evidence_to_claims(text)

        # Find claims with strong links
        linked_claims_set = set()
        for link in links:
            if link.is_strong_link:
                linked_claims_set.add(link.claim)

        linked_count = len(linked_claims_set)
        total = len(claim_analysis.claims)

        # Identify unlinked claims
        unlinked = [c for c in claim_analysis.claims if c not in linked_claims_set]

        # Identify evidence gaps
        gaps = []
        for claim in unlinked[:3]:  # Top 3 gaps
            truncated = claim[:100] + "..." if len(claim) > 100 else claim
            gaps.append(f"No evidence for: {truncated}")

        coverage = linked_count / total if total > 0 else 0.0

        return EvidenceCoverageResult(
            coverage=coverage,
            total_claims=total,
            linked_claims=linked_count,
            unlinked_claims=unlinked,
            evidence_gaps=gaps,
            links=links,
        )


__all__ = [
    "EvidenceLink",
    "ClaimAnalysis",
    "EvidenceCoverageResult",
    "EvidenceClaimLinker",
    "EMBEDDINGS_AVAILABLE",  # noqa: F822 — provided via __getattr__
]
