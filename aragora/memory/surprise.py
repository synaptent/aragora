"""
Unified Surprise Scoring Module.

Consolidates surprise-based memorization logic used across the memory system.
Based on Titans/MIRAS principles - patterns that deviate from expected outcomes
get higher priority for retention.

Key concepts:
- Surprise = |actual - expected|, measuring prediction error
- High surprise → pattern is novel/unexpected → prioritize learning
- Low surprise → pattern is predictable → safe to demote/forget

Usage:
    from aragora.memory.surprise import (
        calculate_surprise,
        calculate_base_rate,
        update_surprise_ema,
        SurpriseScorer,
    )

    # Simple surprise calculation
    surprise = calculate_surprise(actual=1.0, expected=0.3)  # 0.7

    # With exponential moving average
    new_surprise = update_surprise_ema(old_surprise=0.5, new_surprise=0.8)  # ~0.59

    # Full scorer with state
    scorer = SurpriseScorer()
    score = scorer.score_outcome(category="type_errors", is_success=True)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from aragora.core.embeddings.service import UnifiedEmbeddingService

logger = logging.getLogger(__name__)

# Default EMA alpha for surprise smoothing
DEFAULT_SURPRISE_ALPHA = 0.3


def calculate_surprise(
    actual: float,
    expected: float,
    scale_factor: float = 1.0,
    max_surprise: float = 1.0,
) -> float:
    """
    Calculate surprise score as deviation from expectation.

    Args:
        actual: Actual outcome (typically 0.0 for failure, 1.0 for success)
        expected: Expected outcome (base rate, probability estimate)
        scale_factor: Multiplier for the raw surprise (default 1.0)
        max_surprise: Maximum surprise value to return (default 1.0)

    Returns:
        Surprise score in [0, max_surprise]

    Example:
        >>> calculate_surprise(actual=1.0, expected=0.3)
        0.7
        >>> calculate_surprise(actual=0.0, expected=0.9)
        0.9
    """
    raw_surprise = abs(actual - expected)
    scaled = raw_surprise * scale_factor
    return min(max_surprise, scaled)


def calculate_base_rate(
    success_count: int,
    failure_count: int,
    prior: float = 0.5,
    prior_weight: int = 2,
) -> float:
    """
    Calculate base success rate with Bayesian smoothing.

    Uses a Beta prior to avoid extreme rates with few observations.

    Args:
        success_count: Number of successes observed
        failure_count: Number of failures observed
        prior: Prior probability (default 0.5 = uninformative)
        prior_weight: Effective sample size of prior (default 2)

    Returns:
        Smoothed success rate in [0, 1]

    Example:
        >>> calculate_base_rate(success_count=8, failure_count=2)
        0.75
        >>> calculate_base_rate(success_count=0, failure_count=0)
        0.5  # Falls back to prior with no observations
    """
    total = success_count + failure_count
    if total == 0:
        return prior

    # Bayesian smoothing: (successes + prior*weight) / (total + weight)
    smoothed_rate = (success_count + prior * prior_weight) / (total + prior_weight)
    return smoothed_rate


def update_surprise_ema(
    old_surprise: float,
    new_surprise: float,
    alpha: float = DEFAULT_SURPRISE_ALPHA,
) -> float:
    """
    Update surprise score using exponential moving average.

    EMA provides temporal smoothing to avoid overreacting to single events.

    Args:
        old_surprise: Previous surprise score
        new_surprise: Current surprise observation
        alpha: Smoothing factor in (0, 1). Higher = more weight on new value.

    Returns:
        Updated surprise score

    Example:
        >>> update_surprise_ema(old_surprise=0.5, new_surprise=0.8)
        0.59
        >>> update_surprise_ema(old_surprise=0.5, new_surprise=0.8, alpha=0.5)
        0.65
    """
    return old_surprise * (1 - alpha) + new_surprise * alpha


def calculate_combined_surprise(
    success_surprise: float,
    agent_prediction_error: float | None = None,
    success_weight: float = 0.7,
    agent_weight: float = 0.3,
) -> float:
    """
    Combine multiple surprise signals into a single score.

    Useful when you have both outcome surprise and agent calibration error.

    Args:
        success_surprise: Surprise from success/failure rate deviation
        agent_prediction_error: Optional error from agent confidence calibration
        success_weight: Weight for success surprise (default 0.7)
        agent_weight: Weight for agent prediction error (default 0.3)

    Returns:
        Combined surprise score in [0, 1]
    """
    if agent_prediction_error is None:
        return success_surprise

    combined = success_weight * success_surprise + agent_weight * agent_prediction_error
    return min(1.0, combined)


@dataclass
class CategoryStats:
    """Statistics for a category used in surprise calculation."""

    success_count: int = 0
    failure_count: int = 0
    current_surprise: float = 0.0

    @property
    def total(self) -> int:
        """Total observations."""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Raw success rate (no smoothing)."""
        if self.total == 0:
            return 0.5
        return self.success_count / self.total


@dataclass
class SurpriseScorer:
    """
    Stateful surprise scorer that tracks category statistics.

    Maintains per-category base rates and surprise scores, providing
    a unified interface for surprise-based learning.

    Example:
        scorer = SurpriseScorer()

        # Score outcomes
        s1 = scorer.score_outcome("type_errors", is_success=True)
        s2 = scorer.score_outcome("type_errors", is_success=False)

        # Get category stats
        stats = scorer.get_category_stats("type_errors")
        print(f"Success rate: {stats.success_rate:.2%}")
    """

    alpha: float = DEFAULT_SURPRISE_ALPHA
    scale_factor: float = 1.0
    prior: float = 0.5
    prior_weight: int = 2

    _categories: dict[str, CategoryStats] = field(default_factory=dict)

    def score_outcome(
        self,
        category: str,
        is_success: bool,
        agent_prediction_error: float | None = None,
    ) -> float:
        """
        Score an outcome and update category statistics.

        Args:
            category: Category/type of the pattern (e.g., "type_errors", "logic_bugs")
            is_success: Whether this was a successful outcome
            agent_prediction_error: Optional agent calibration error

        Returns:
            Updated surprise score for this category
        """
        # Get or create category stats
        if category not in self._categories:
            self._categories[category] = CategoryStats()

        stats = self._categories[category]

        # Calculate base rate before updating counts
        base_rate = calculate_base_rate(
            stats.success_count,
            stats.failure_count,
            prior=self.prior,
            prior_weight=self.prior_weight,
        )

        # Calculate surprise for this outcome
        actual = 1.0 if is_success else 0.0
        new_surprise = calculate_surprise(
            actual=actual,
            expected=base_rate,
            scale_factor=self.scale_factor,
        )

        # Combine with agent prediction error if provided
        if agent_prediction_error is not None:
            new_surprise = calculate_combined_surprise(
                success_surprise=new_surprise,
                agent_prediction_error=agent_prediction_error,
            )

        # Update stats
        if is_success:
            stats.success_count += 1
        else:
            stats.failure_count += 1

        # Update surprise with EMA
        stats.current_surprise = update_surprise_ema(
            old_surprise=stats.current_surprise,
            new_surprise=new_surprise,
            alpha=self.alpha,
        )

        return stats.current_surprise

    def get_category_stats(self, category: str) -> CategoryStats | None:
        """Get statistics for a category."""
        return self._categories.get(category)

    def get_all_categories(self) -> dict[str, CategoryStats]:
        """Get all category statistics."""
        return self._categories.copy()

    def get_category_surprise(self, category: str) -> float:
        """Get current surprise score for a category."""
        stats = self._categories.get(category)
        return stats.current_surprise if stats else 0.0

    def reset_category(self, category: str) -> None:
        """Reset statistics for a category."""
        if category in self._categories:
            del self._categories[category]

    def reset_all(self) -> None:
        """Reset all category statistics."""
        self._categories.clear()


# Database-aware surprise calculation helpers


def calculate_surprise_from_db_row(
    success_count: int,
    failure_count: int,
    is_success: bool,
    old_surprise: float = 0.0,
    alpha: float = DEFAULT_SURPRISE_ALPHA,
    scale_factor: float = 1.0,
) -> float:
    """
    Calculate updated surprise score from database statistics.

    Convenience function for updating surprise when you have counts from a DB query.

    Args:
        success_count: Number of successes in database
        failure_count: Number of failures in database
        is_success: Whether current outcome is a success
        old_surprise: Previous surprise score
        alpha: EMA smoothing factor
        scale_factor: Surprise scale factor

    Returns:
        Updated surprise score
    """
    base_rate = calculate_base_rate(success_count, failure_count)
    actual = 1.0 if is_success else 0.0
    new_surprise = calculate_surprise(actual, base_rate, scale_factor)
    return update_surprise_ema(old_surprise, new_surprise, alpha)


# ---------------------------------------------------------------------------
# Titans-inspired content surprise scoring for unified memory writes
# ---------------------------------------------------------------------------

import re
import time as _time
import uuid as _uuid
from collections import deque


@dataclass(frozen=True)
class ContentSurpriseScore:
    """Result of Titans-inspired surprise scoring for a memory write candidate."""

    novelty: float  # 0-1, how unexpected vs current memory state
    momentum: float  # 0-1, how connected to recent surprise chain
    combined: float  # weighted: 0.7*novelty + 0.3*momentum
    should_store: bool  # combined >= threshold
    reason: str  # human-readable explanation


@dataclass
class SurpriseChainConfig:
    """Configuration for surprise chain tracking."""

    chain_ttl_seconds: float = 300.0  # 5 minutes — chain expires after this
    relatedness_threshold: float = 0.3  # keyword overlap to consider "related"
    chain_bonus_per_link: float = 0.05  # bonus per related surprising item
    max_chain_bonus: float = 0.25  # cap on chain amplification
    min_surprise_to_chain: float = 0.4  # only chain items above this surprise


@dataclass(frozen=True)
class EnrichedSurpriseScore(ContentSurpriseScore):
    """Extended surprise score with chain context."""

    chain_length: int = 0
    chain_bonus: float = 0.0
    chain_id: str | None = None


@dataclass
class _SurpriseChain:
    """Internal chain state."""

    id: str
    keywords: set[str]
    length: int = 1
    last_updated: float = 0.0


class SurpriseChainTracker:
    """Tracks chains of related surprising items for momentum amplification.

    When several surprising items arrive in quick succession on the same
    topic, the chain bonus amplifies the combined surprise signal — the
    "momentum" aspect of Titans.
    """

    def __init__(self, config: SurpriseChainConfig | None = None):
        self.config = config or SurpriseChainConfig()
        self._chains: list[_SurpriseChain] = []

    def enrich(
        self, score: ContentSurpriseScore, content_keywords: set[str]
    ) -> EnrichedSurpriseScore:
        """Enrich a base score with chain context.

        If the item is surprising enough (>= min_surprise_to_chain) and
        relates to an active chain, the chain bonus is applied.
        """
        self._expire_chains()

        # Below minimum surprise — don't start or extend chains
        if score.combined < self.config.min_surprise_to_chain:
            return EnrichedSurpriseScore(
                novelty=score.novelty,
                momentum=score.momentum,
                combined=score.combined,
                should_store=score.should_store,
                reason=score.reason,
            )

        chain = self._find_matching_chain(content_keywords)
        now = _time.monotonic()

        if chain is not None:
            # Extend existing chain
            chain.length += 1
            chain.keywords |= content_keywords
            chain.last_updated = now

            bonus = min(
                self.config.max_chain_bonus,
                (chain.length - 1) * self.config.chain_bonus_per_link,
            )
            enriched_combined = min(1.0, round(score.combined + bonus, 4))
            return EnrichedSurpriseScore(
                novelty=score.novelty,
                momentum=score.momentum,
                combined=enriched_combined,
                should_store=enriched_combined >= score.combined or score.should_store,
                reason=score.reason,
                chain_length=chain.length,
                chain_bonus=round(bonus, 4),
                chain_id=chain.id,
            )

        # Start new chain
        new_chain = _SurpriseChain(
            id=str(_uuid.uuid4()),
            keywords=set(content_keywords),
            length=1,
            last_updated=now,
        )
        self._chains.append(new_chain)

        return EnrichedSurpriseScore(
            novelty=score.novelty,
            momentum=score.momentum,
            combined=score.combined,
            should_store=score.should_store,
            reason=score.reason,
            chain_length=1,
            chain_bonus=0.0,
            chain_id=new_chain.id,
        )

    def _find_matching_chain(self, keywords: set[str]) -> _SurpriseChain | None:
        """Find the best matching active chain by keyword overlap."""
        best: _SurpriseChain | None = None
        best_overlap = 0.0

        for chain in self._chains:
            if not keywords or not chain.keywords:
                continue
            overlap = len(keywords & chain.keywords) / max(len(keywords), 1)
            if overlap >= self.config.relatedness_threshold and overlap > best_overlap:
                best = chain
                best_overlap = overlap

        return best

    def _expire_chains(self) -> None:
        """Remove chains that have exceeded their TTL."""
        now = _time.monotonic()
        self._chains = [
            c for c in self._chains if (now - c.last_updated) < self.config.chain_ttl_seconds
        ]

    @property
    def active_chain_count(self) -> int:
        """Number of active (non-expired) chains."""
        self._expire_chains()
        return len(self._chains)


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase keyword tokens from text."""
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if len(w) >= 3}


class ContentSurpriseScorer:
    """Titans-inspired surprise scoring for memory writes.

    Scores how novel/surprising a piece of information is relative
    to what the system already knows. High-surprise items get stored;
    routine items are discarded or stored at lower tiers.

    Reference: arXiv:2501.00663 - Titans: Learning to Memorize at Test Time
    """

    NOVELTY_WEIGHT = 0.7
    MOMENTUM_WEIGHT = 0.3

    def __init__(
        self,
        threshold: float = 0.3,
        momentum_window: int = 100,
        chain_config: SurpriseChainConfig | None = None,
    ):
        self._threshold = threshold
        self._recent_topics: deque[str] = deque(maxlen=momentum_window)
        self._recent_surprises: deque[float] = deque(maxlen=momentum_window)
        self._chain_tracker: SurpriseChainTracker | None = (
            SurpriseChainTracker(chain_config) if chain_config is not None else None
        )

    @property
    def threshold(self) -> float:
        return self._threshold

    def score(
        self,
        content: str,
        source: str,
        existing_context: str = "",
    ) -> ContentSurpriseScore:
        """Score surprise using keyword overlap as a lightweight proxy.

        Args:
            content: The new content to evaluate.
            source: Where this content came from (e.g. "debate", "document").
            existing_context: What the system already knows about this topic.

        Returns:
            ContentSurpriseScore with novelty, momentum, and combined score.
        """
        content_kw = _extract_keywords(content)
        if not content_kw:
            return ContentSurpriseScore(
                novelty=0.0,
                momentum=0.0,
                combined=0.0,
                should_store=False,
                reason="No extractable keywords",
            )

        # --- Novelty ---
        if existing_context:
            context_kw = _extract_keywords(existing_context)
            if context_kw:
                overlap = len(content_kw & context_kw)
                novelty = 1.0 - (overlap / max(len(content_kw), 1))
            else:
                novelty = 1.0  # no prior context → fully novel
        else:
            novelty = 1.0

        # --- Momentum ---
        momentum = self._compute_momentum(content_kw)

        # --- Combined ---
        combined = round(
            self.NOVELTY_WEIGHT * novelty + self.MOMENTUM_WEIGHT * momentum,
            4,
        )
        should_store = combined >= self._threshold

        # Build reason
        if combined >= 0.7:
            reason = f"High surprise ({combined:.2f}): novel content from {source}"
        elif should_store:
            reason = f"Moderate surprise ({combined:.2f}): worth storing from {source}"
        else:
            reason = f"Low surprise ({combined:.2f}): routine content from {source}"

        # Track for momentum
        self._recent_topics.append(" ".join(sorted(content_kw)[:10]))
        self._recent_surprises.append(combined)

        base_score = ContentSurpriseScore(
            novelty=round(novelty, 4),
            momentum=round(momentum, 4),
            combined=combined,
            should_store=should_store,
            reason=reason,
        )

        # Enrich with chain tracking if configured
        if self._chain_tracker is not None:
            return self._chain_tracker.enrich(base_score, content_kw)

        return base_score

    def score_debate_outcome(
        self,
        conclusion: str,
        domain: str,
        confidence: float,
        prior_conclusions: list[str] | None = None,
    ) -> ContentSurpriseScore:
        """Specialised scorer for debate outcomes.

        High surprise if: conclusion contradicts prior consensus, new domain,
        or unanimous agreement on previously contentious topic.
        """
        prior_text = "\n".join(prior_conclusions) if prior_conclusions else ""
        base = self.score(
            content=f"[{domain}] {conclusion} (confidence={confidence:.2f})",
            source="debate",
            existing_context=prior_text,
        )

        # Boost novelty for high-confidence outcomes in new territory
        novelty = base.novelty
        if not prior_conclusions:
            novelty = min(1.0, novelty + 0.2)
        elif confidence >= 0.9 and novelty > 0.4:
            novelty = min(1.0, novelty + 0.1)

        combined = round(
            self.NOVELTY_WEIGHT * novelty + self.MOMENTUM_WEIGHT * base.momentum,
            4,
        )
        return ContentSurpriseScore(
            novelty=round(novelty, 4),
            momentum=base.momentum,
            combined=combined,
            should_store=combined >= self._threshold,
            reason=base.reason,
        )

    def _compute_momentum(self, content_kw: set[str]) -> float:
        """Momentum = how related to recent *surprising* topics."""
        if not self._recent_topics or not self._recent_surprises:
            return 0.5  # neutral when no history

        recent_kw: set[str] = set()
        for topic in list(self._recent_topics)[-20:]:
            recent_kw.update(topic.split())

        if not recent_kw:
            return 0.5

        overlap = len(content_kw & recent_kw)
        relatedness = overlap / max(len(content_kw), 1)

        recent = list(self._recent_surprises)[-10:]
        avg_surprise = sum(recent) / len(recent) if recent else 0.5

        return min(1.0, relatedness * 0.6 + avg_surprise * 0.4)


class EmbeddingSurpriseScorer(ContentSurpriseScorer):
    """Semantic surprise scorer using embedding cosine distance.

    Replaces keyword overlap with embedding similarity for more
    accurate novelty detection (catches paraphrases, synonyms).
    Falls back to keyword-based scoring if embedding fails.
    """

    def __init__(
        self,
        threshold: float = 0.3,
        momentum_window: int = 100,
        embedding_service: UnifiedEmbeddingService | None = None,
        embedding_cache_size: int = 1000,
        chain_config: SurpriseChainConfig | None = None,
    ):
        super().__init__(
            threshold=threshold,
            momentum_window=momentum_window,
            chain_config=chain_config,
        )
        self._embedding_service = embedding_service
        self._embedding_cache: dict[str, list[float]] = {}
        self._embedding_cache_size = embedding_cache_size

    def score(
        self,
        content: str,
        source: str,
        existing_context: str = "",
    ) -> ContentSurpriseScore:
        """Score surprise using embedding similarity when possible.

        Falls back to keyword-based scoring on embedding failure.
        """
        # Try embedding-based novelty
        embedding_novelty = self._compute_embedding_novelty(content, existing_context)

        if embedding_novelty is None:
            # Fallback to keyword-based
            return super().score(content, source, existing_context)

        content_kw = _extract_keywords(content)

        # Use embedding novelty instead of keyword overlap
        novelty = embedding_novelty

        # Momentum is still keyword-based (topic relatedness, not novelty precision)
        momentum = self._compute_momentum(content_kw) if content_kw else 0.5

        combined = round(
            self.NOVELTY_WEIGHT * novelty + self.MOMENTUM_WEIGHT * momentum,
            4,
        )
        should_store = combined >= self._threshold

        if combined >= 0.7:
            reason = f"High surprise ({combined:.2f}): novel content from {source} [embedding]"
        elif should_store:
            reason = f"Moderate surprise ({combined:.2f}): worth storing from {source} [embedding]"
        else:
            reason = f"Low surprise ({combined:.2f}): routine content from {source} [embedding]"

        # Track for momentum
        if content_kw:
            self._recent_topics.append(" ".join(sorted(content_kw)[:10]))
        self._recent_surprises.append(combined)

        base_score = ContentSurpriseScore(
            novelty=round(novelty, 4),
            momentum=round(momentum, 4),
            combined=combined,
            should_store=should_store,
            reason=reason,
        )

        # Enrich with chain tracking if configured
        if self._chain_tracker is not None and content_kw:
            return self._chain_tracker.enrich(base_score, content_kw)

        return base_score

    def _compute_embedding_novelty(self, content: str, context: str) -> float | None:
        """Compute novelty as cosine distance between embeddings.

        Returns None on failure (no service, error, etc.).
        """
        if not self._embedding_service or not context:
            return None

        try:
            content_emb = self._get_embedding(content)
            context_emb = self._get_embedding(context)

            if content_emb is None or context_emb is None:
                return None

            # Cosine similarity
            dot = sum(a * b for a, b in zip(content_emb, context_emb))
            norm_a = math.sqrt(sum(a * a for a in content_emb))
            norm_b = math.sqrt(sum(b * b for b in context_emb))

            if norm_a < 1e-10 or norm_b < 1e-10:
                return 1.0  # Zero vector → fully novel

            similarity = dot / (norm_a * norm_b)
            # Novelty = 1 - similarity (cosine distance)
            return max(0.0, min(1.0, 1.0 - similarity))

        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.warning("Embedding novelty computation failed: %s", e)
            return None

    def _get_embedding(self, text: str) -> list[float] | None:
        """Get embedding for text, with caching.

        Uses a sync wrapper around the async embed service.
        """
        # Cache key: hash of first 200 chars
        cache_key = hashlib.sha256(text[:200].encode("utf-8", errors="ignore")).hexdigest()[:16]

        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        embedding_service = cast(Any, self._embedding_service)
        try:
            # Sync wrapper — run the async embed in a new event loop if needed
            loop: asyncio.AbstractEventLoop | None = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if loop is not None and loop.is_running():
                # Already in an async context — can't nest; use thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, embedding_service.embed(text))
                    result = future.result(timeout=10)
            else:
                result = asyncio.run(embedding_service.embed(text))

            embedding = result.embedding

            # Evict oldest if cache full
            if len(self._embedding_cache) >= self._embedding_cache_size:
                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]

            self._embedding_cache[cache_key] = embedding
            return embedding

        except (RuntimeError, ValueError, TypeError, OSError, TimeoutError) as e:
            logger.warning("Failed to get embedding: %s", e)
            return None


# Type alias for custom base rate calculators
BaseRateCalculator = Callable[[str], float]


def create_db_base_rate_calculator(
    query_func: Callable[[str], tuple[int, int]],
) -> BaseRateCalculator:
    """
    Create a base rate calculator that queries a database.

    Args:
        query_func: Function that takes category and returns (success_count, failure_count)

    Returns:
        Callable that calculates base rate for a category

    Example:
        def query_db(category: str) -> tuple[int, int]:
            cursor.execute("SELECT success_count, failure_count FROM stats WHERE cat = ?", (category,))
            row = cursor.fetchone()
            return (row[0], row[1]) if row else (0, 0)

        calc_base_rate = create_db_base_rate_calculator(query_db)
        rate = calc_base_rate("type_errors")  # Queries DB and calculates rate
    """

    def calculator(category: str) -> float:
        success, failure = query_func(category)
        return calculate_base_rate(success, failure)

    return calculator
