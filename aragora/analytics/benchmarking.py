"""
Decision Benchmarking Module.

Enables SMEs to compare their decision metrics against anonymized industry
benchmarks with k-anonymity and differential privacy (Laplace mechanism).

Categories:
- By industry: healthcare, financial, legal, technology
- By team_size: 1-5, 6-20, 21-100, 100+
- By decision_type: vendor, hiring, architecture, pricing, incident

Usage:
    from aragora.analytics.benchmarking import (
        BenchmarkAggregator,
        BenchmarkMetric,
    )

    agg = BenchmarkAggregator()
    agg.record_decision(
        tenant_id="t1",
        category="healthcare",
        metrics={"consensus_rate": 0.85, "confidence_avg": 0.72},
    )
    benchmarks = agg.compute_benchmarks("healthcare")
    comparison = agg.compare({"consensus_rate": 0.90}, "healthcare")
"""

from __future__ import annotations

import logging
import math
import random
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Canonical metric names tracked by the aggregator
BENCHMARK_METRICS = (
    "consensus_rate",
    "confidence_avg",
    "time_to_decision",
    "cost_per_decision",
    "calibration_score",
)

# Industry categories
INDUSTRY_CATEGORIES = ("healthcare", "financial", "legal", "technology")

# Team-size bucket boundaries (spec: 1-5, 6-20, 21-100, 100+)
TEAM_SIZE_BUCKETS = {
    "1-5": (1, 5),
    "6-20": (6, 20),
    "21-100": (21, 100),
    "100+": (101, float("inf")),
}

# Decision type categories
DECISION_TYPE_CATEGORIES = ("vendor", "hiring", "architecture", "pricing", "incident")

# Minimum data points for k-anonymity (default)
DEFAULT_MIN_K = 5

# Default Laplace epsilon for differential privacy
DEFAULT_EPSILON = 1.0


def _bucket_team_size(size: int) -> str:
    """Return a privacy-safe team-size bucket label.

    Args:
        size: Number of team members.

    Returns:
        One of "1-5", "6-20", "21-100", "100+".
    """
    for label, (lo, hi) in TEAM_SIZE_BUCKETS.items():
        if lo <= size <= hi:
            return label
    return "100+"


def _laplace_noise(epsilon: float, sensitivity: float = 1.0) -> float:
    """Generate Laplace mechanism noise for differential privacy.

    Args:
        epsilon: Privacy budget parameter. Higher = less noise = less privacy.
        sensitivity: Query sensitivity (default 1.0).

    Returns:
        Random noise sample from Laplace(0, sensitivity/epsilon).
    """
    if epsilon <= 0:
        return 0.0
    scale = sensitivity / epsilon
    # Laplace distribution via inverse CDF
    u = random.random() - 0.5
    return -scale * math.copysign(1, u) * math.log1p(-2 * abs(u))


@dataclass
class BenchmarkMetric:
    """Aggregated benchmark percentiles for one category + metric.

    Attributes:
        category: Industry vertical or decision type (e.g. "healthcare").
        metric: Metric name (e.g. "consensus_rate").
        p25: 25th percentile value.
        p50: 50th percentile (median) value.
        p75: 75th percentile value.
        p90: 90th percentile value.
        sample_count: Number of tenants contributing (for k-anonymity).
        computed_at: When this benchmark was computed.
    """

    category: str
    metric: str
    p25: float
    p50: float
    p75: float
    p90: float
    sample_count: int
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "category": self.category,
            "metric": self.metric,
            "p25": round(self.p25, 4),
            "p50": round(self.p50, 4),
            "p75": round(self.p75, 4),
            "p90": round(self.p90, 4),
            "sample_count": self.sample_count,
            "computed_at": self.computed_at.isoformat(),
        }


# Backward-compatible alias
BenchmarkAggregate = BenchmarkMetric


@dataclass
class _DecisionRecord:
    """Internal record of a single decision's metrics."""

    tenant_id: str
    category: str
    metrics: dict[str, float]
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BenchmarkAggregator:
    """Computes anonymized decision-quality percentiles with k-anonymity.

    Only emits benchmarks when at least *min_k* distinct tenants contribute
    to a bucket. Differential noise (Laplace mechanism) is added to each
    percentile value to further protect individual tenant data.

    Args:
        min_k: Minimum distinct tenants per bucket for k-anonymity. Default 5.
        epsilon: Laplace mechanism privacy budget. Default 1.0.
        noise_scale: Legacy parameter (ignored if epsilon is set). If provided
            and epsilon is not explicitly set, enables Gaussian noise mode
            for backward compatibility.
    """

    def __init__(
        self,
        min_k: int = DEFAULT_MIN_K,
        epsilon: float = DEFAULT_EPSILON,
        noise_scale: float | None = None,
    ) -> None:
        self.min_k = max(1, min_k)
        self.epsilon = epsilon
        # Backward compat: if noise_scale passed explicitly, use old Gaussian mode
        self._use_gaussian = noise_scale is not None
        self._gaussian_scale = noise_scale if noise_scale is not None else 0.0
        self._records: list[_DecisionRecord] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_decision(
        self,
        tenant_id: str,
        category: str,
        metrics: dict[str, float],
        *,
        # Legacy keyword arguments for backward compatibility
        industry: str | None = None,
        team_size: int | None = None,
        decision_type: str | None = None,
    ) -> None:
        """Record a single decision's quality metrics.

        Args:
            tenant_id: Opaque tenant identifier (used only for k-counting).
            category: Benchmark category (e.g. "healthcare", "1-5", "vendor").
            metrics: Mapping of metric name to float value.
            industry: (Legacy) Industry vertical. If provided with team_size
                and decision_type, builds a composite category.
            team_size: (Legacy) Number of team members.
            decision_type: (Legacy) Decision type string.
        """
        # Legacy composite-category support
        if industry is not None:
            bucket = _bucket_team_size(team_size) if team_size else "unknown"
            dtype = decision_type or "unknown"
            composite_cat = f"{industry}/{bucket}/{dtype}"
            # Record under all three dimension categories + the composite
            filtered = {k: v for k, v in metrics.items() if k in BENCHMARK_METRICS}
            with self._lock:
                # Composite category (for backward compat with get_benchmarks)
                self._records.append(
                    _DecisionRecord(
                        tenant_id=tenant_id,
                        category=composite_cat,
                        metrics=filtered,
                    )
                )
                # Also record under individual dimension categories
                for cat in [industry, bucket, dtype]:
                    if cat and cat != "unknown":
                        self._records.append(
                            _DecisionRecord(
                                tenant_id=tenant_id,
                                category=cat,
                                metrics=filtered,
                            )
                        )
            return

        # Standard single-category recording
        filtered = {k: v for k, v in metrics.items() if k in BENCHMARK_METRICS}
        record = _DecisionRecord(
            tenant_id=tenant_id,
            category=category,
            metrics=filtered,
        )
        with self._lock:
            self._records.append(record)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def compute_benchmarks(self, category: str) -> list[BenchmarkMetric]:
        """Compute percentile benchmarks for a specific category.

        Only returns results if at least min_k distinct tenants contributed.
        Applies differential noise (Laplace mechanism) to protect privacy.

        Args:
            category: The category to compute benchmarks for.

        Returns:
            List of BenchmarkMetric, one per metric with enough data.
            Empty list if k-anonymity threshold not met.
        """
        with self._lock:
            records = [r for r in self._records if r.category == category]

        # k-anonymity check
        distinct_tenants = {r.tenant_id for r in records}
        if len(distinct_tenants) < self.min_k:
            logger.debug(
                "Skipping category %s: only %d tenants (need %d)",
                category,
                len(distinct_tenants),
                self.min_k,
            )
            return []

        now = datetime.now(timezone.utc)
        benchmarks: list[BenchmarkMetric] = []

        for metric_name in BENCHMARK_METRICS:
            values = sorted(r.metrics[metric_name] for r in records if metric_name in r.metrics)
            if not values:
                continue

            benchmarks.append(
                BenchmarkMetric(
                    category=category,
                    metric=metric_name,
                    p25=self._percentile(values, 25),
                    p50=self._percentile(values, 50),
                    p75=self._percentile(values, 75),
                    p90=self._percentile(values, 90),
                    sample_count=len(values),
                    computed_at=now,
                )
            )

        return benchmarks

    def compute_aggregates(self) -> list[BenchmarkMetric]:
        """Compute percentile benchmarks across all categories.

        Returns only groups that satisfy k-anonymity (>= min_k distinct tenants).
        This is the legacy API; prefer compute_benchmarks(category) for
        targeted queries.
        """
        with self._lock:
            records = list(self._records)

        # Group by category
        groups: dict[str, list[_DecisionRecord]] = defaultdict(list)
        for r in records:
            groups[r.category].append(r)

        now = datetime.now(timezone.utc)
        aggregates: list[BenchmarkMetric] = []

        for category in sorted(groups):
            group_records = groups[category]
            distinct_tenants = {r.tenant_id for r in group_records}
            if len(distinct_tenants) < self.min_k:
                continue

            for metric_name in BENCHMARK_METRICS:
                values = sorted(
                    r.metrics[metric_name] for r in group_records if metric_name in r.metrics
                )
                if not values:
                    continue

                aggregates.append(
                    BenchmarkMetric(
                        category=category,
                        metric=metric_name,
                        p25=self._percentile(values, 25),
                        p50=self._percentile(values, 50),
                        p75=self._percentile(values, 75),
                        p90=self._percentile(values, 90),
                        sample_count=len(values),
                        computed_at=now,
                    )
                )

        return aggregates

    def compare(
        self,
        tenant_metrics: dict[str, float],
        category: str,
        # Legacy parameter name
        team_size_bucket: str | None = None,
    ) -> dict[str, Any]:
        """Compare a tenant's metrics against benchmarks for a category.

        Returns a dict mapping each metric name to its percentile rank
        relative to the benchmark distribution.

        Args:
            tenant_metrics: Dict of metric_name -> value for the tenant.
            category: Benchmark category to compare against.
            team_size_bucket: (Legacy) If provided along with category being
                an industry, builds composite category "industry/bucket/*".

        Returns:
            Dict mapping metric name to comparison data including
            value, percentile_rank, benchmark_p50, benchmark_p75.
        """
        # Legacy composite-category lookup
        if team_size_bucket is not None:
            benchmarks = self.get_benchmarks(category, team_size_bucket)
        else:
            benchmarks = self.compute_benchmarks(category)

        # Build a lookup: metric_name -> BenchmarkMetric
        by_metric: dict[str, BenchmarkMetric] = {}
        for b in benchmarks:
            by_metric.setdefault(b.metric, b)

        comparison: dict[str, Any] = {}
        for metric_name, value in tenant_metrics.items():
            if metric_name not in by_metric:
                continue
            agg = by_metric[metric_name]
            rank = self._estimate_percentile_rank(value, agg)
            comparison[metric_name] = {
                "value": value,
                "percentile_rank": rank,
                "benchmark_p50": agg.p50,
                "benchmark_p75": agg.p75,
            }
        return comparison

    def group_by(
        self,
        debates: list[dict[str, Any]],
        key: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Group debate dicts by a specified key.

        Supports grouping by ``industry``, ``team_size_bucket``, or
        ``decision_type``.  When *key* is ``"team_size_bucket"`` the raw
        ``team_size`` integer in each debate is mapped to a privacy-safe
        bucket label via :func:`_bucket_team_size`.

        Args:
            debates: List of debate dictionaries.
            key: One of ``"industry"``, ``"team_size_bucket"``, ``"decision_type"``.

        Returns:
            Dict mapping each distinct group value to its list of debates.
        """
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for debate in debates:
            if key == "team_size_bucket":
                raw = debate.get("team_size")
                if raw is not None:
                    group_val = _bucket_team_size(int(raw))
                else:
                    group_val = "unknown"
            else:
                group_val = str(debate.get(key, "unknown"))
            groups[group_val].append(debate)
        return dict(groups)

    @staticmethod
    def _add_noise(value: float, epsilon: float = 0.1) -> float:
        """Add Laplace differential privacy noise to a value.

        This is a convenience wrapper around :func:`_laplace_noise` for
        callers that want to perturb individual values.

        Args:
            value: The value to perturb.
            epsilon: Privacy budget parameter (default 0.1).

        Returns:
            The value with added Laplace noise.
        """
        return value + _laplace_noise(epsilon)

    def get_categories(self) -> list[str]:
        """List available benchmark categories that have enough data.

        Returns:
            Sorted list of category strings with >= min_k distinct tenants.
        """
        with self._lock:
            records = list(self._records)

        groups: dict[str, set[str]] = defaultdict(set)
        for r in records:
            groups[r.category].add(r.tenant_id)

        return sorted(cat for cat, tenants in groups.items() if len(tenants) >= self.min_k)

    def get_benchmarks(
        self,
        industry: str,
        team_size_bucket: str,
        decision_type: str | None = None,
    ) -> list[BenchmarkMetric]:
        """Return benchmarks filtered by industry and team-size bucket.

        This is the legacy API for composite categories. Internally
        delegates to compute_aggregates with prefix matching.

        Args:
            industry: Industry to filter on.
            team_size_bucket: Team-size bucket ("small", "medium", etc.).
            decision_type: Optional decision-type filter.
        """
        all_aggs = self.compute_aggregates()
        prefix = f"{industry}/{team_size_bucket}/"
        results = [a for a in all_aggs if a.category.startswith(prefix)]
        if decision_type:
            results = [
                a for a in results if a.category == f"{industry}/{team_size_bucket}/{decision_type}"
            ]
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _percentile(self, sorted_values: list[float], pct: int) -> float:
        """Compute a percentile with linear interpolation + differential noise."""
        n = len(sorted_values)
        if n == 0:
            return 0.0
        if n == 1:
            return sorted_values[0] + self._noise()

        k = (pct / 100.0) * (n - 1)
        lo = int(k)
        hi = min(lo + 1, n - 1)
        frac = k - lo
        raw = sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])
        return raw + self._noise()

    def _noise(self) -> float:
        """Generate differential privacy noise.

        Uses Laplace mechanism by default (epsilon-based).
        Falls back to Gaussian for backward compatibility.
        """
        if self._use_gaussian:
            if self._gaussian_scale <= 0:
                return 0.0
            return random.gauss(0, self._gaussian_scale)
        return _laplace_noise(self.epsilon)

    @staticmethod
    def _estimate_percentile_rank(value: float, agg: BenchmarkMetric) -> int:
        """Estimate which percentile a value falls into."""
        if value <= agg.p25:
            return 25
        if value <= agg.p50:
            return 50
        if value <= agg.p75:
            return 75
        if value <= agg.p90:
            return 90
        return 95


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_aggregator: BenchmarkAggregator | None = None
_agg_lock = threading.Lock()


def get_benchmark_aggregator() -> BenchmarkAggregator:
    """Get or create the global BenchmarkAggregator instance."""
    global _aggregator
    if _aggregator is None:
        with _agg_lock:
            if _aggregator is None:
                _aggregator = BenchmarkAggregator()
    return _aggregator


__all__ = [
    "BENCHMARK_METRICS",
    "DECISION_TYPE_CATEGORIES",
    "DEFAULT_EPSILON",
    "DEFAULT_MIN_K",
    "INDUSTRY_CATEGORIES",
    "TEAM_SIZE_BUCKETS",
    "BenchmarkAggregate",
    "BenchmarkAggregator",
    "BenchmarkMetric",
    "get_benchmark_aggregator",
]
