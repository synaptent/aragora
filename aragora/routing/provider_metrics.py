"""Per-provider cost/quality metrics tracking.

Provides in-memory storage of debate outcome metrics per provider,
with optional JSON persistence for cross-session continuity.

Usage:
    store = ProviderMetricsStore()
    store.record_debate_outcome("anthropic", cost=0.12, quality=0.85, latency=3.2)
    metrics = store.get_metrics("anthropic")
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProviderMetrics:
    """Aggregated metrics for a single provider."""

    provider_name: str
    total_debates: int = 0
    total_cost: float = 0.0
    avg_cost_per_debate: float = 0.0
    avg_quality_score: float = 0.0
    consensus_rate: float = 0.0
    failure_rate: float = 0.0
    p95_latency_seconds: float = 0.0
    last_updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "provider_name": self.provider_name,
            "total_debates": self.total_debates,
            "total_cost": self.total_cost,
            "avg_cost_per_debate": self.avg_cost_per_debate,
            "avg_quality_score": self.avg_quality_score,
            "consensus_rate": self.consensus_rate,
            "failure_rate": self.failure_rate,
            "p95_latency_seconds": self.p95_latency_seconds,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderMetrics:
        """Deserialize from dictionary."""
        return cls(
            provider_name=data["provider_name"],
            total_debates=data.get("total_debates", 0),
            total_cost=data.get("total_cost", 0.0),
            avg_cost_per_debate=data.get("avg_cost_per_debate", 0.0),
            avg_quality_score=data.get("avg_quality_score", 0.0),
            consensus_rate=data.get("consensus_rate", 0.0),
            failure_rate=data.get("failure_rate", 0.0),
            p95_latency_seconds=data.get("p95_latency_seconds", 0.0),
            last_updated=data.get("last_updated", ""),
        )


@dataclass
class _ProviderAccumulator:
    """Internal accumulator for computing running metrics."""

    total_debates: int = 0
    total_cost: float = 0.0
    quality_sum: float = 0.0
    consensus_count: int = 0
    failure_count: int = 0
    latencies: list[float] = field(default_factory=list)
    last_updated: str = ""


class ProviderMetricsStore:
    """In-memory store for per-provider debate outcome metrics.

    Thread-safe. Optionally persists to a JSON file for cross-session use.

    Args:
        persist_path: Optional file path for JSON persistence.
            If provided, metrics are loaded on init and saved after each update.
    """

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._accumulators: dict[str, _ProviderAccumulator] = {}
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path and self._persist_path.exists():
            self._load()

    def record_debate_outcome(
        self,
        provider: str,
        *,
        cost: float = 0.0,
        quality: float = 0.0,
        latency: float = 0.0,
        consensus_reached: bool = False,
        failed: bool = False,
    ) -> None:
        """Record the outcome of a debate for a given provider.

        Args:
            provider: Provider name (e.g. "anthropic", "openai").
            cost: Total cost in USD for this debate.
            quality: Quality score in [0, 1].
            latency: Latency in seconds for this debate.
            consensus_reached: Whether consensus was achieved.
            failed: Whether the provider call failed.
        """
        with self._lock:
            acc = self._accumulators.setdefault(provider, _ProviderAccumulator())
            acc.total_debates += 1
            acc.total_cost += cost
            acc.quality_sum += quality
            acc.latencies.append(latency)
            if consensus_reached:
                acc.consensus_count += 1
            if failed:
                acc.failure_count += 1
            acc.last_updated = datetime.now(timezone.utc).isoformat()

        if self._persist_path:
            self._save()

    def get_metrics(self, provider: str) -> ProviderMetrics | None:
        """Get aggregated metrics for a provider.

        Returns None if no data has been recorded for the provider.
        """
        with self._lock:
            acc = self._accumulators.get(provider)
            if acc is None or acc.total_debates == 0:
                return None
            return self._compute_metrics(provider, acc)

    def get_all_metrics(self) -> dict[str, ProviderMetrics]:
        """Get aggregated metrics for all providers."""
        with self._lock:
            result: dict[str, ProviderMetrics] = {}
            for provider, acc in self._accumulators.items():
                if acc.total_debates > 0:
                    result[provider] = self._compute_metrics(provider, acc)
            return result

    def get_top_providers(
        self, metric: str = "avg_quality_score", n: int = 5
    ) -> list[ProviderMetrics]:
        """Get top N providers sorted by a given metric.

        Args:
            metric: Field name on ProviderMetrics to sort by.
                Valid values: avg_quality_score, avg_cost_per_debate,
                consensus_rate, failure_rate, p95_latency_seconds.
            n: Number of providers to return.

        Returns:
            List of ProviderMetrics sorted descending by the metric
            (ascending for cost/failure/latency metrics).
        """
        all_metrics = self.get_all_metrics()
        if not all_metrics:
            return []

        # Lower-is-better metrics should sort ascending
        ascending_metrics = {"avg_cost_per_debate", "failure_rate", "p95_latency_seconds"}
        reverse = metric not in ascending_metrics

        sorted_providers = sorted(
            all_metrics.values(),
            key=lambda m: getattr(m, metric, 0.0),
            reverse=reverse,
        )
        return sorted_providers[:n]

    def _compute_metrics(self, provider: str, acc: _ProviderAccumulator) -> ProviderMetrics:
        """Compute aggregated metrics from an accumulator."""
        n = acc.total_debates
        p95_latency = 0.0
        if acc.latencies:
            sorted_latencies = sorted(acc.latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p95_idx = min(p95_idx, len(sorted_latencies) - 1)
            p95_latency = sorted_latencies[p95_idx]

        return ProviderMetrics(
            provider_name=provider,
            total_debates=n,
            total_cost=acc.total_cost,
            avg_cost_per_debate=acc.total_cost / n if n > 0 else 0.0,
            avg_quality_score=acc.quality_sum / n if n > 0 else 0.0,
            consensus_rate=acc.consensus_count / n if n > 0 else 0.0,
            failure_rate=acc.failure_count / n if n > 0 else 0.0,
            p95_latency_seconds=p95_latency,
            last_updated=acc.last_updated,
        )

    def _save(self) -> None:
        """Persist accumulators to JSON file."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            with self._lock:
                for provider, acc in self._accumulators.items():
                    data[provider] = {
                        "total_debates": acc.total_debates,
                        "total_cost": acc.total_cost,
                        "quality_sum": acc.quality_sum,
                        "consensus_count": acc.consensus_count,
                        "failure_count": acc.failure_count,
                        "latencies": acc.latencies,
                        "last_updated": acc.last_updated,
                    }
            self._persist_path.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("Failed to persist provider metrics: %s", e)

    def _load(self) -> None:
        """Load accumulators from JSON file."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text())
            for provider, acc_data in raw.items():
                acc = _ProviderAccumulator(
                    total_debates=acc_data.get("total_debates", 0),
                    total_cost=acc_data.get("total_cost", 0.0),
                    quality_sum=acc_data.get("quality_sum", 0.0),
                    consensus_count=acc_data.get("consensus_count", 0),
                    failure_count=acc_data.get("failure_count", 0),
                    latencies=acc_data.get("latencies", []),
                    last_updated=acc_data.get("last_updated", ""),
                )
                self._accumulators[provider] = acc
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load provider metrics: %s", e)


__all__ = [
    "ProviderMetrics",
    "ProviderMetricsStore",
]
