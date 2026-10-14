"""
Advanced convergence analyzer for multi-metric debate analysis.

Provides a nuanced view of convergence beyond simple text similarity by
considering argument diversity, evidence overlap, and stance stability.
"""

from __future__ import annotations

import logging
import re

from aragora.debate.convergence.cache import (
    PairwiseSimilarityCache,
    cleanup_similarity_cache,
    get_pairwise_similarity_cache,
)
from aragora.debate.convergence.metrics import (
    AdvancedConvergenceMetrics,
    ArgumentDiversityMetric,
    EvidenceConvergenceMetric,
    StanceVolatilityMetric,
)
from aragora.debate.similarity.backends import (
    SimilarityBackend,
    get_similarity_backend,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Advanced Convergence Analyzer
# =============================================================================


class AdvancedConvergenceAnalyzer:
    """
    Analyzes debate convergence using multiple metrics.

    Provides a more nuanced view than simple text similarity by
    considering argument diversity, evidence overlap, and stance stability.

    Performance optimizations:
    - Session-scoped pairwise similarity cache
    - Batch computation for vectorizable backends
    - Early termination for non-converged states
    """

    def __init__(
        self,
        similarity_backend: SimilarityBackend | None = None,
        debate_id: str | None = None,
        enable_cache: bool = True,
    ):
        """
        Initialize analyzer.

        Args:
            similarity_backend: Backend for text similarity (auto-selects if None)
            debate_id: Unique debate ID for session-scoped caching
            enable_cache: Whether to enable pairwise similarity caching
        """
        if similarity_backend is None:
            # Use factory function for consistent backend selection
            self.backend: SimilarityBackend = get_similarity_backend("auto")
        else:
            self.backend = similarity_backend

        # Session-scoped pairwise similarity cache
        self._debate_id = debate_id
        self._enable_cache = enable_cache and debate_id is not None
        self._similarity_cache: PairwiseSimilarityCache | None = None

        if self._enable_cache and debate_id:
            self._similarity_cache = get_pairwise_similarity_cache(debate_id)
            logger.debug("AdvancedConvergenceAnalyzer caching enabled: debate=%s", debate_id)

    def _compute_similarity_cached(self, text1: str, text2: str) -> float:
        """
        Compute similarity with session-scoped caching.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Check cache first
        if self._similarity_cache:
            cached = self._similarity_cache.get(text1, text2)
            if cached is not None:
                return cached

        # Compute similarity
        similarity = self.backend.compute_similarity(text1, text2)

        # Cache the result
        if self._similarity_cache:
            self._similarity_cache.put(text1, text2, similarity)

        return similarity

    def cleanup(self) -> None:
        """Cleanup resources when debate ends."""
        if self._debate_id:
            cleanup_similarity_cache(self._debate_id)
            logger.debug("AdvancedConvergenceAnalyzer cleanup: debate=%s", self._debate_id)

    def get_cache_stats(self) -> dict | None:
        """Get cache statistics."""
        if self._similarity_cache:
            return self._similarity_cache.get_stats()
        return None

    def extract_arguments(self, text: str) -> list[str]:
        """
        Extract distinct arguments/claims from text.

        Simple heuristic: split by sentence and filter.
        """
        # Split into sentences
        sentences = re.split(r"[.!?]+", text)

        # Filter to substantive sentences (> 5 words)
        arguments = []
        for s in sentences:
            s = s.strip()
            if len(s.split()) > 5:
                arguments.append(s)

        return arguments

    def extract_citations(self, text: str) -> set[str]:
        """
        Extract citations/sources from text.

        Looks for URLs, academic-style citations, and quoted sources.
        """
        citations = set()

        # URLs
        urls = re.findall(r'https?://[^\s<>"]+', text)
        citations.update(urls)

        # Academic citations like (Author, 2024) or [1]
        academic = re.findall(r"\([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}\)", text)
        citations.update(academic)

        # Numbered citations [1], [2], etc.
        numbered = re.findall(r"\[\d+\]", text)
        citations.update(numbered)

        # Quoted sources "According to X"
        quoted = re.findall(
            r"(?:according to|per|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", text, re.I
        )
        citations.update(quoted)

        return citations

    def detect_stance(self, text: str) -> str:
        """
        Detect the stance/position in text.

        Returns: "support", "oppose", "neutral", or "mixed"
        """
        text_lower = text.lower()

        # Strong support indicators
        support_patterns = (
            r"\b(agree|support|favor|endorse|recommend|should|must|definitely|certainly)\b"
        )
        support_count = len(re.findall(support_patterns, text_lower))

        # Strong oppose indicators
        oppose_patterns = (
            r"\b(disagree|oppose|against|reject|shouldn\'t|must not|definitely not|certainly not)\b"
        )
        oppose_count = len(re.findall(oppose_patterns, text_lower))

        # Neutral indicators
        neutral_patterns = r"\b(depends|unclear|both|however|on the other hand|alternatively)\b"
        neutral_count = len(re.findall(neutral_patterns, text_lower))

        # Determine stance
        if support_count > oppose_count and support_count > neutral_count:
            return "support"
        elif oppose_count > support_count and oppose_count > neutral_count:
            return "oppose"
        elif neutral_count > 0 and support_count > 0 and oppose_count > 0:
            return "mixed"
        else:
            return "neutral"

    def compute_argument_diversity(
        self,
        agent_responses: dict[str, str],
        use_optimized: bool = True,
    ) -> ArgumentDiversityMetric:
        """
        Compute argument diversity across agents.

        High diversity = agents making different points.

        Args:
            agent_responses: Dict mapping agent names to their response texts
            use_optimized: Use O(n log n) ANN-based algorithm when possible
                          (falls back to O(n^2) if embeddings unavailable)

        Returns:
            ArgumentDiversityMetric with unique/total counts and diversity score
        """
        all_arguments: list[str] = []
        for text in agent_responses.values():
            all_arguments.extend(self.extract_arguments(text))

        if not all_arguments:
            return ArgumentDiversityMetric(
                unique_arguments=0,
                total_arguments=0,
                diversity_score=0.0,
            )

        # Try optimized path using vectorized similarity computation
        if use_optimized and len(all_arguments) >= 5:
            try:
                unique_count, total, diversity_score = self._compute_diversity_optimized(
                    all_arguments
                )
                return ArgumentDiversityMetric(
                    unique_arguments=unique_count,
                    total_arguments=total,
                    diversity_score=diversity_score,
                )
            except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
                logger.debug("Optimized diversity computation failed, using fallback: %s", e)

        # Fallback: O(n^2) pairwise comparison with caching
        # Arguments with < 0.7 similarity to all others are "unique"
        # Uses session-scoped cache to avoid redundant computations
        unique_count = 0
        for i, arg in enumerate(all_arguments):
            is_unique = True
            for j, other in enumerate(all_arguments):
                if i != j:
                    # Use cached similarity to avoid redundant computations
                    sim = self._compute_similarity_cached(arg, other)
                    if sim > 0.7:
                        is_unique = False
                        break
            if is_unique:
                unique_count += 1

        diversity_score = unique_count / len(all_arguments) if all_arguments else 0.0

        return ArgumentDiversityMetric(
            unique_arguments=unique_count,
            total_arguments=len(all_arguments),
            diversity_score=diversity_score,
        )

    def _compute_diversity_optimized(
        self, arguments: list[str], threshold: float = 0.7
    ) -> tuple[int, int, float]:
        """Compute diversity using optimized vectorized operations.

        Uses SentenceTransformer embeddings + vectorized numpy/FAISS operations
        for O(n log n) complexity instead of O(n^2).

        Args:
            arguments: List of argument texts
            threshold: Similarity threshold for considering arguments as duplicates

        Returns:
            Tuple of (unique_count, total_count, diversity_score)
        """
        import numpy as np

        from aragora.debate.similarity.ann import count_unique_fast

        # Get embeddings from backend if it supports it
        if hasattr(self.backend, "_get_embedding"):
            # SentenceTransformerBackend has _get_embedding
            embeddings = []
            for arg in arguments:
                emb = self.backend._get_embedding(arg)
                embeddings.append(emb)
            embeddings_array = np.vstack(embeddings)
        elif hasattr(self.backend, "vectorizer"):
            # TFIDFBackend has vectorizer
            from scipy.sparse import issparse

            tfidf_matrix = self.backend.vectorizer.fit_transform(arguments)
            if issparse(tfidf_matrix):
                embeddings_array = tfidf_matrix.toarray().astype(np.float32)
            else:
                embeddings_array = tfidf_matrix.astype(np.float32)
        else:
            # JaccardBackend or unknown - can't use optimized path
            raise ValueError("Backend doesn't support embedding extraction")

        return count_unique_fast(embeddings_array, threshold=threshold)

    def compute_evidence_convergence(
        self,
        agent_responses: dict[str, str],
    ) -> EvidenceConvergenceMetric:
        """
        Compute evidence/citation overlap across agents.

        High overlap = agents citing same sources.
        """
        all_citations: list[set[str]] = []
        for text in agent_responses.values():
            all_citations.append(self.extract_citations(text))

        # Flatten for total count
        all_unique = set().union(*all_citations) if all_citations else set()
        total = len(all_unique)

        if total == 0 or len(all_citations) < 2:
            return EvidenceConvergenceMetric(
                shared_citations=0,
                total_citations=0,
                overlap_score=0.0,
            )

        # Find citations shared by at least 2 agents
        shared = set()
        for citation in all_unique:
            count = sum(1 for agent_cites in all_citations if citation in agent_cites)
            if count >= 2:
                shared.add(citation)

        overlap_score = len(shared) / total if total > 0 else 0.0

        return EvidenceConvergenceMetric(
            shared_citations=len(shared),
            total_citations=total,
            overlap_score=overlap_score,
        )

    def compute_stance_volatility(
        self,
        response_history: list[dict[str, str]],
    ) -> StanceVolatilityMetric:
        """
        Compute stance volatility across rounds.

        Args:
            response_history: List of {agent: response} dicts per round

        Returns:
            StanceVolatilityMetric
        """
        if len(response_history) < 2:
            return StanceVolatilityMetric(
                stance_changes=0,
                total_responses=0,
                volatility_score=0.0,
            )

        # Track stance per agent per round
        agent_stances: dict[str, list[str]] = {}
        for round_responses in response_history:
            for agent, text in round_responses.items():
                if agent not in agent_stances:
                    agent_stances[agent] = []
                agent_stances[agent].append(self.detect_stance(text))

        # Count stance changes
        total_changes = 0
        total_responses = 0
        for agent, stances in agent_stances.items():
            total_responses += len(stances)
            for i in range(1, len(stances)):
                if stances[i] != stances[i - 1]:
                    total_changes += 1

        volatility_score = total_changes / max(1, total_responses - len(agent_stances))

        return StanceVolatilityMetric(
            stance_changes=total_changes,
            total_responses=total_responses,
            volatility_score=min(1.0, volatility_score),
        )

    def analyze(
        self,
        current_responses: dict[str, str],
        previous_responses: dict[str, str] | None = None,
        response_history: list[dict[str, str]] | None = None,
        domain: str = "general",
    ) -> AdvancedConvergenceMetrics:
        """
        Perform comprehensive convergence analysis.

        Args:
            current_responses: {agent: response} for current round
            previous_responses: {agent: response} for previous round (optional)
            response_history: Full history of responses (optional)
            domain: Debate domain for context

        Returns:
            AdvancedConvergenceMetrics with all computed metrics
        """
        # Compute semantic similarity with caching
        if previous_responses:
            common_agents = set(current_responses.keys()) & set(previous_responses.keys())
            if common_agents:
                similarities = []
                for agent in common_agents:
                    # Use cached similarity to avoid redundant computations
                    sim = self._compute_similarity_cached(
                        current_responses[agent],
                        previous_responses[agent],
                    )
                    similarities.append(sim)
                semantic_sim = sum(similarities) / len(similarities)
            else:
                semantic_sim = 0.0
        else:
            semantic_sim = 0.0

        # Compute advanced metrics
        arg_diversity = self.compute_argument_diversity(current_responses)
        evidence_conv = self.compute_evidence_convergence(current_responses)

        stance_vol = None
        if response_history:
            stance_vol = self.compute_stance_volatility(response_history)

        # Build result
        metrics = AdvancedConvergenceMetrics(
            semantic_similarity=semantic_sim,
            argument_diversity=arg_diversity,
            evidence_convergence=evidence_conv,
            stance_volatility=stance_vol,
            domain=domain,
        )

        # Compute overall score
        metrics.compute_overall_score()

        return metrics
