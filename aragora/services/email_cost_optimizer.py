"""
Cost Optimization Layer for Email Prioritization.

Minimizes API costs while maintaining prioritization quality through:
- Result caching with TTL
- Batch processing for multiple emails
- Intelligent tier selection based on confidence
- Request deduplication
- Token usage tracking
- Budget enforcement

Usage:
    from aragora.services.email_cost_optimizer import (
        CostOptimizedPrioritizer,
        CostConfig,
    )

    optimizer = CostOptimizedPrioritizer(
        prioritizer=email_prioritizer,
        config=CostConfig(
            daily_budget_usd=10.0,
            cache_ttl_seconds=3600,
        ),
    )

    # Single email (uses cache if available)
    result = await optimizer.score_email(email)

    # Batch processing (more efficient)
    results = await optimizer.batch_score_emails(emails)

    # Check usage
    stats = optimizer.get_usage_stats()
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.models import EmailMessage
    from aragora.services.email_prioritization import (
        EmailPrioritizer,
        EmailPriorityResult,
    )


from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


@dataclass
class CostConfig:
    """Configuration for cost optimization."""

    # Budget limits
    daily_budget_usd: float = 10.0
    monthly_budget_usd: float = 200.0
    per_request_limit_usd: float = 0.50

    # Caching
    cache_ttl_seconds: int = 3600  # 1 hour
    cache_max_size: int = 10000
    cache_score_threshold: float = 0.9  # Only cache high-confidence results

    # Batching
    batch_size: int = 10
    batch_timeout_seconds: float = 0.5

    # Tier selection
    tier_1_cost: float = 0.0  # Free (rule-based)
    tier_2_cost: float = 0.001  # ~$0.001 per email (single agent)
    tier_3_cost: float = 0.01  # ~$0.01 per email (multi-agent debate)

    # Rate limiting
    max_requests_per_minute: int = 60
    max_tier_3_per_hour: int = 100

    # Optimization thresholds
    skip_tier_2_confidence: float = 0.85  # Skip tier 2 if tier 1 is this confident
    skip_tier_3_confidence: float = 0.75  # Skip tier 3 if tier 2 is this confident
    force_tier_1_for_bulk: bool = True  # Only use tier 1 for bulk emails


@dataclass
class UsageStats:
    """Usage statistics for cost tracking."""

    # Request counts
    total_requests: int = 0
    tier_1_requests: int = 0
    tier_2_requests: int = 0
    tier_3_requests: int = 0

    # Cache stats
    cache_hits: int = 0
    cache_misses: int = 0

    # Token usage (approximate)
    input_tokens: int = 0
    output_tokens: int = 0

    # Costs
    estimated_cost_usd: float = 0.0
    daily_cost_usd: float = 0.0
    monthly_cost_usd: float = 0.0

    # Timing
    total_processing_time_ms: float = 0.0
    avg_processing_time_ms: float = 0.0

    # Period tracking
    day_start: datetime = field(default_factory=datetime.now)
    month_start: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_requests": self.total_requests,
            "tier_1_requests": self.tier_1_requests,
            "tier_2_requests": self.tier_2_requests,
            "tier_3_requests": self.tier_3_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": (
                self.cache_hits / (self.cache_hits + self.cache_misses)
                if (self.cache_hits + self.cache_misses) > 0
                else 0.0
            ),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "daily_cost_usd": round(self.daily_cost_usd, 4),
            "monthly_cost_usd": round(self.monthly_cost_usd, 4),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
        }


@dataclass
class CacheEntry:
    """Cached prioritization result."""

    result: EmailPriorityResult
    timestamp: datetime
    email_hash: str
    confidence: float


class CostOptimizedPrioritizer:
    """
    Cost-optimized wrapper for email prioritization.

    Provides caching, batching, and intelligent tier selection
    to minimize API costs while maintaining quality.
    """

    def __init__(
        self,
        prioritizer: EmailPrioritizer,
        config: CostConfig | None = None,
    ):
        """
        Initialize cost optimizer.

        Args:
            prioritizer: Underlying email prioritizer
            config: Cost optimization configuration
        """
        self.prioritizer = prioritizer
        self.config = config or CostConfig()

        # Cache
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = asyncio.Lock()

        # Usage tracking
        self._stats = UsageStats()
        self._stats_lock = asyncio.Lock()

        # Rate limiting
        self._request_timestamps: list[datetime] = []
        self._tier_3_timestamps: list[datetime] = []
        self._rate_lock = asyncio.Lock()

        # Batch queue
        self._batch_queue: list[tuple[EmailMessage, asyncio.Future]] = []
        self._batch_lock = asyncio.Lock()
        self._batch_task: asyncio.Task | None = None

    def _compute_email_hash(self, email: EmailMessage) -> str:
        """Compute a hash for caching purposes."""
        # Use key fields that affect prioritization
        key_data = {
            "from": email.from_address.lower(),
            "subject": email.subject[:200] if email.subject else "",
            "snippet": email.snippet[:200] if hasattr(email, "snippet") else "",
            "labels": sorted(email.labels) if email.labels else [],
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    async def _get_cached_result(
        self,
        email: EmailMessage,
    ) -> EmailPriorityResult | None:
        """Get cached result if available and valid."""
        email_hash = self._compute_email_hash(email)

        async with self._cache_lock:
            if email_hash in self._cache:
                entry = self._cache[email_hash]

                # Check TTL
                age = (datetime.now() - entry.timestamp).total_seconds()
                if age < self.config.cache_ttl_seconds:
                    async with self._stats_lock:
                        self._stats.cache_hits += 1
                    return entry.result

                # Expired - remove from cache
                del self._cache[email_hash]

        async with self._stats_lock:
            self._stats.cache_misses += 1

        return None

    async def _cache_result(
        self,
        email: EmailMessage,
        result: EmailPriorityResult,
    ) -> None:
        """Cache a result if it meets quality threshold."""
        # Only cache high-confidence results
        if result.confidence < self.config.cache_score_threshold:
            return

        email_hash = self._compute_email_hash(email)

        async with self._cache_lock:
            # Enforce cache size limit
            if len(self._cache) >= self.config.cache_max_size:
                # Remove oldest entries
                sorted_entries = sorted(
                    self._cache.items(),
                    key=lambda x: x[1].timestamp,
                )
                for key, _ in sorted_entries[: len(sorted_entries) // 4]:
                    del self._cache[key]

            self._cache[email_hash] = CacheEntry(
                result=result,
                timestamp=datetime.now(),
                email_hash=email_hash,
                confidence=result.confidence,
            )

    async def _check_rate_limits(self) -> bool:
        """Check if we're within rate limits."""
        now = datetime.now()

        async with self._rate_lock:
            # Clean old timestamps
            minute_ago = now - timedelta(minutes=1)
            hour_ago = now - timedelta(hours=1)

            self._request_timestamps = [ts for ts in self._request_timestamps if ts > minute_ago]
            self._tier_3_timestamps = [ts for ts in self._tier_3_timestamps if ts > hour_ago]

            # Check limits
            if len(self._request_timestamps) >= self.config.max_requests_per_minute:
                return False

            return True

    async def _record_request(
        self,
        tier: int,
        processing_time_ms: float,
    ) -> None:
        """Record a request for tracking."""
        now = datetime.now()

        async with self._rate_lock:
            self._request_timestamps.append(now)
            if tier == 3:
                self._tier_3_timestamps.append(now)

        async with self._stats_lock:
            self._stats.total_requests += 1
            self._stats.total_processing_time_ms += processing_time_ms

            if tier == 1:
                self._stats.tier_1_requests += 1
                cost = self.config.tier_1_cost
            elif tier == 2:
                self._stats.tier_2_requests += 1
                cost = self.config.tier_2_cost
            else:
                self._stats.tier_3_requests += 1
                cost = self.config.tier_3_cost

            self._stats.estimated_cost_usd += cost
            self._stats.daily_cost_usd += cost
            self._stats.monthly_cost_usd += cost

            # Update average
            if self._stats.total_requests > 0:
                self._stats.avg_processing_time_ms = (
                    self._stats.total_processing_time_ms / self._stats.total_requests
                )

            # Reset daily/monthly counters if needed
            if self._stats.day_start.date() != now.date():
                self._stats.daily_cost_usd = cost
                self._stats.day_start = now

            if self._stats.month_start.month != now.month:
                self._stats.monthly_cost_usd = cost
                self._stats.month_start = now

    async def _check_budget(self) -> bool:
        """Check if we're within budget."""
        async with self._stats_lock:
            if self._stats.daily_cost_usd >= self.config.daily_budget_usd:
                logger.warning(
                    "Daily budget exceeded: $%.2f >= $%.2f",
                    self._stats.daily_cost_usd,
                    self.config.daily_budget_usd,
                )
                return False

            if self._stats.monthly_cost_usd >= self.config.monthly_budget_usd:
                logger.warning(
                    "Monthly budget exceeded: $%.2f >= $%.2f",
                    self._stats.monthly_cost_usd,
                    self.config.monthly_budget_usd,
                )
                return False

            return True

    def _select_optimal_tier(
        self,
        email: EmailMessage,
        tier_1_result: EmailPriorityResult | None = None,
    ) -> int:
        """
        Select the optimal scoring tier based on confidence and cost.

        Returns tier number (1, 2, or 3)
        """
        # Check if we can afford higher tiers
        if not run_async(self._check_budget()):
            return 1  # Budget exceeded, use free tier only

        # If tier 1 gave high confidence, stop there
        if tier_1_result and tier_1_result.confidence >= self.config.skip_tier_2_confidence:
            return 1

        # Check tier 3 rate limit
        async def check_tier_3():
            async with self._rate_lock:
                if len(self._tier_3_timestamps) >= self.config.max_tier_3_per_hour:
                    return False
                return True

        can_use_tier_3 = run_async(check_tier_3())

        # For bulk/newsletter emails, stick to tier 1
        if self.config.force_tier_1_for_bulk and tier_1_result:
            from aragora.services.email_prioritization import EmailPriority

            if tier_1_result.priority == EmailPriority.DEFER:
                return 1

        # Otherwise use tier 2, and maybe tier 3 if needed
        if can_use_tier_3:
            return 2  # Start with tier 2, may escalate to 3
        else:
            return 2  # Use tier 2 only

    async def score_email(
        self,
        email: EmailMessage,
        force_tier: int | None = None,
        skip_cache: bool = False,
    ) -> EmailPriorityResult:
        """
        Score a single email with cost optimization.

        Args:
            email: Email to score
            force_tier: Force a specific tier (1, 2, or 3)
            skip_cache: Skip cache lookup

        Returns:
            EmailPriorityResult
        """
        start_time = time.time()

        # Check cache first
        if not skip_cache:
            cached = await self._get_cached_result(email)
            if cached:
                return cached

        # Check rate limits
        if not await self._check_rate_limits():
            # Over rate limit - return tier 1 result only
            from aragora.services.email_prioritization import ScoringTier

            result = await self.prioritizer.score_email(
                email,
                force_tier=ScoringTier.TIER_1_RULES,
            )
            result.rationale += " (rate limited to tier 1)"
            return result

        # Determine tier
        if force_tier:
            from aragora.services.email_prioritization import ScoringTier

            tier_map = {
                1: ScoringTier.TIER_1_RULES,
                2: ScoringTier.TIER_2_LIGHTWEIGHT,
                3: ScoringTier.TIER_3_DEBATE,
            }
            result = await self.prioritizer.score_email(
                email,
                force_tier=tier_map.get(force_tier),
            )
            tier_used = force_tier
        else:
            # Score with tier 1 first
            from aragora.services.email_prioritization import ScoringTier

            result = await self.prioritizer.score_email(
                email,
                force_tier=ScoringTier.TIER_1_RULES,
            )
            tier_used = 1

            # Check if we need higher tiers
            if result.confidence < self.config.skip_tier_2_confidence:
                if await self._check_budget():
                    # Try tier 2
                    tier_2_result = await self.prioritizer.score_email(
                        email,
                        force_tier=ScoringTier.TIER_2_LIGHTWEIGHT,
                    )
                    tier_used = 2

                    # Check if tier 2 is confident enough
                    if tier_2_result.confidence > result.confidence:
                        result = tier_2_result

                    # Escalate to tier 3 if still not confident
                    if (
                        result.confidence < self.config.skip_tier_3_confidence
                        and await self._check_budget()
                    ):
                        async with self._rate_lock:
                            if len(self._tier_3_timestamps) < self.config.max_tier_3_per_hour:
                                tier_3_result = await self.prioritizer.score_email(
                                    email,
                                    force_tier=ScoringTier.TIER_3_DEBATE,
                                )
                                if tier_3_result.confidence > result.confidence:
                                    result = tier_3_result
                                    tier_used = 3

        # Record stats
        processing_time = (time.time() - start_time) * 1000
        await self._record_request(tier_used, processing_time)

        # Cache result
        await self._cache_result(email, result)

        return result

    async def batch_score_emails(
        self,
        emails: list[EmailMessage],
        max_concurrent: int = 5,
    ) -> list[EmailPriorityResult]:
        """
        Score multiple emails with batch optimization.

        Args:
            emails: List of emails to score
            max_concurrent: Maximum concurrent scoring operations

        Returns:
            List of EmailPriorityResult in same order as input
        """
        # Check cache for all emails first
        results: list[EmailPriorityResult | None] = [None] * len(emails)
        uncached_indices: list[int] = []

        for i, email in enumerate(emails):
            cached = await self._get_cached_result(email)
            if cached:
                results[i] = cached
            else:
                uncached_indices.append(i)

        if not uncached_indices:
            # All results were cached, so no None placeholders remain
            return results  # type: ignore[return-value]

        # Score uncached emails with concurrency limit
        semaphore = asyncio.Semaphore(max_concurrent)

        async def score_with_limit(index: int) -> tuple[int, EmailPriorityResult]:
            async with semaphore:
                result = await self.score_email(emails[index], skip_cache=True)
                return index, result

        tasks = [score_with_limit(i) for i in uncached_indices]
        scored = await asyncio.gather(*tasks)

        for index, result in scored:
            results[index] = result

        # All indices have been populated, so no None placeholders remain
        return results  # type: ignore[return-value]

    def get_usage_stats(self) -> UsageStats:
        """Get current usage statistics."""
        return self._stats

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self.config.cache_max_size,
            "hit_rate": (
                self._stats.cache_hits / (self._stats.cache_hits + self._stats.cache_misses)
                if (self._stats.cache_hits + self._stats.cache_misses) > 0
                else 0.0
            ),
            "hits": self._stats.cache_hits,
            "misses": self._stats.cache_misses,
        }

    async def clear_cache(self) -> int:
        """Clear the result cache. Returns number of entries cleared."""
        async with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def reset_stats(self) -> None:
        """Reset usage statistics."""
        self._stats = UsageStats()

    async def get_cost_projection(
        self,
        emails_per_day: int,
        tier_distribution: dict[int, float] | None = None,
    ) -> dict[str, Any]:
        """
        Project costs based on expected volume.

        Args:
            emails_per_day: Expected emails to process per day
            tier_distribution: Optional tier distribution (e.g., {1: 0.7, 2: 0.2, 3: 0.1})

        Returns:
            Cost projection dict
        """
        if tier_distribution is None:
            # Assume typical distribution
            tier_distribution = {1: 0.70, 2: 0.25, 3: 0.05}

        daily_cost = (
            emails_per_day * tier_distribution.get(1, 0) * self.config.tier_1_cost
            + emails_per_day * tier_distribution.get(2, 0) * self.config.tier_2_cost
            + emails_per_day * tier_distribution.get(3, 0) * self.config.tier_3_cost
        )

        # Account for cache hits (assume 40% hit rate)
        cache_hit_rate = 0.4
        daily_cost *= 1 - cache_hit_rate

        return {
            "emails_per_day": emails_per_day,
            "projected_daily_cost_usd": round(daily_cost, 4),
            "projected_monthly_cost_usd": round(daily_cost * 30, 2),
            "projected_yearly_cost_usd": round(daily_cost * 365, 2),
            "tier_distribution": tier_distribution,
            "assumed_cache_hit_rate": cache_hit_rate,
            "within_daily_budget": daily_cost <= self.config.daily_budget_usd,
            "within_monthly_budget": daily_cost * 30 <= self.config.monthly_budget_usd,
        }


# Factory function
async def create_cost_optimized_prioritizer(
    gmail_connector: Any | None = None,
    knowledge_mound: Any | None = None,
    config: CostConfig | None = None,
) -> CostOptimizedPrioritizer:
    """
    Create a cost-optimized prioritizer.

    Args:
        gmail_connector: Gmail connector
        knowledge_mound: Knowledge Mound
        config: Cost configuration

    Returns:
        CostOptimizedPrioritizer
    """
    from aragora.services.email_prioritization import EmailPrioritizer

    prioritizer = EmailPrioritizer(
        gmail_connector=gmail_connector,
        knowledge_mound=knowledge_mound,
    )

    return CostOptimizedPrioritizer(
        prioritizer=prioritizer,
        config=config,
    )
