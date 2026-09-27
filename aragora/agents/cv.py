"""
Agent Curriculum Vitae (CV) - Unified capability profiles.

Aggregates data from ELO, calibration, and performance systems into
a unified profile for intelligent agent selection.

Inspired by gastown's agent capability tracking pattern.

Example:
    from aragora.agents.cv import CVBuilder, AgentCV

    builder = CVBuilder(elo_system=elo, calibration_tracker=tracker)
    cv = builder.build_cv("claude-opus")

    # Use in selection
    score = cv.compute_selection_score(domain="code")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.agents.calibration import CalibrationTracker
    from aragora.ranking.elo import EloSystem

logger = logging.getLogger(__name__)

__all__ = [
    "AgentCV",
    "ReliabilityMetrics",
    "DomainPerformance",
    "CVBuilder",
    "get_cv_builder",
]


@dataclass
class ReliabilityMetrics:
    """Reliability statistics for an agent."""

    success_rate: float = 0.0  # 0.0-1.0
    failure_rate: float = 0.0  # 0.0-1.0
    timeout_rate: float = 0.0  # 0.0-1.0
    total_calls: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    @property
    def is_reliable(self) -> bool:
        """Check if agent meets reliability threshold (>90% success)."""
        return self.success_rate >= 0.9 and self.total_calls >= 5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "timeout_rate": self.timeout_rate,
            "total_calls": self.total_calls,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "is_reliable": self.is_reliable,
        }


@dataclass
class DomainPerformance:
    """Performance metrics for a specific domain."""

    domain: str
    elo: float = 1000.0
    win_rate: float = 0.0
    debates_count: int = 0
    calibration_accuracy: float = 0.0
    brier_score: float = 1.0  # 0=perfect, 1=worst

    @property
    def has_meaningful_data(self) -> bool:
        """Check if there's enough data for this domain."""
        return self.debates_count >= 3

    @property
    def composite_score(self) -> float:
        """Compute composite domain score (higher is better)."""
        if not self.has_meaningful_data:
            return 0.0

        # Normalize components to 0-1 range
        elo_score = (self.elo - 800) / 400  # 800-1200 → 0-1
        elo_score = max(0.0, min(1.0, elo_score))

        calibration_score = 1 - self.brier_score  # Invert brier

        # Weighted combination
        return 0.4 * elo_score + 0.3 * self.win_rate + 0.3 * calibration_score

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "domain": self.domain,
            "elo": self.elo,
            "win_rate": self.win_rate,
            "debates_count": self.debates_count,
            "calibration_accuracy": self.calibration_accuracy,
            "brier_score": self.brier_score,
            "composite_score": self.composite_score,
            "has_meaningful_data": self.has_meaningful_data,
        }


@dataclass
class AgentCV:
    """
    Unified agent capability profile (Curriculum Vitae).

    Aggregates data from multiple sources:
    - ELO ratings (overall + per-domain)
    - Calibration metrics (Brier score, ECE, accuracy)
    - Reliability stats (success rate, latency)
    - Domain expertise
    - Learned strengths

    Use CVBuilder to construct instances from raw data sources.
    """

    # Identity
    agent_id: str
    model_name: str = ""

    # Overall ratings
    overall_elo: float = 1000.0
    overall_win_rate: float = 0.0
    total_debates: int = 0

    # Calibration
    calibration_accuracy: float = 0.0
    brier_score: float = 1.0  # 0=perfect, 1=worst
    expected_calibration_error: float = 1.0
    calibration_bias: str = "unknown"  # "overconfident", "underconfident", "well-calibrated"

    # Reliability
    reliability: ReliabilityMetrics = field(default_factory=ReliabilityMetrics)

    # Domain expertise
    domain_performance: dict[str, DomainPerformance] = field(default_factory=dict)

    # Learning trajectory
    learning_category: str = "unknown"  # "rapid", "steady", "slow", "declining"
    elo_gain_rate: float = 0.0  # ELO points per debate

    # Model capabilities (static, from registry)
    model_capabilities: list[str] = field(default_factory=list)

    # Learned strengths (extracted from winning patterns)
    learned_strengths: list[str] = field(default_factory=list)

    # Metadata
    updated_at: datetime = field(default_factory=datetime.now)
    data_sources: list[str] = field(default_factory=list)

    @property
    def has_meaningful_data(self) -> bool:
        """Check if CV has enough data for reliable selection."""
        return self.total_debates >= 5 or self.reliability.total_calls >= 10

    @property
    def best_domains(self) -> list[str]:
        """Get domains where this agent excels (sorted by score)."""
        sorted_domains = sorted(
            [d for d in self.domain_performance.values() if d.has_meaningful_data],
            key=lambda d: d.composite_score,
            reverse=True,
        )
        return [d.domain for d in sorted_domains[:5]]

    @property
    def is_well_calibrated(self) -> bool:
        """Check if agent is well-calibrated (low ECE)."""
        return self.expected_calibration_error < 0.15

    def get_domain_score(self, domain: str) -> float:
        """Get composite score for a specific domain."""
        if domain in self.domain_performance:
            return self.domain_performance[domain].composite_score
        return 0.0

    def compute_selection_score(
        self,
        domain: str | None = None,
        elo_weight: float = 0.3,
        calibration_weight: float = 0.2,
        reliability_weight: float = 0.2,
        domain_weight: float = 0.3,
    ) -> float:
        """
        Compute a selection score for team selection.

        Args:
            domain: Target domain (optional)
            elo_weight: Weight for ELO component
            calibration_weight: Weight for calibration component
            reliability_weight: Weight for reliability component
            domain_weight: Weight for domain expertise

        Returns:
            Selection score (higher is better)
        """
        score = 0.0

        # ELO component (normalize 800-1200 to 0-1)
        elo_score = (self.overall_elo - 800) / 400
        elo_score = max(0.0, min(1.0, elo_score))
        score += elo_score * elo_weight

        # Calibration component (invert brier, 0=worst, 1=best)
        calibration_score = 1 - self.brier_score
        score += calibration_score * calibration_weight

        # Reliability component
        score += self.reliability.success_rate * reliability_weight

        # Domain component
        if domain:
            domain_score = self.get_domain_score(domain)
            score += domain_score * domain_weight
        else:
            # Use win rate as fallback
            score += self.overall_win_rate * domain_weight

        return score

    def to_dict(self) -> dict[str, Any]:
        """Convert CV to dictionary representation."""
        return {
            "agent_id": self.agent_id,
            "model_name": self.model_name,
            "overall_elo": self.overall_elo,
            "overall_win_rate": self.overall_win_rate,
            "total_debates": self.total_debates,
            "calibration_accuracy": self.calibration_accuracy,
            "brier_score": self.brier_score,
            "expected_calibration_error": self.expected_calibration_error,
            "calibration_bias": self.calibration_bias,
            "reliability": self.reliability.to_dict(),
            "domain_performance": {k: v.to_dict() for k, v in self.domain_performance.items()},
            "learning_category": self.learning_category,
            "elo_gain_rate": self.elo_gain_rate,
            "model_capabilities": self.model_capabilities,
            "learned_strengths": self.learned_strengths,
            "best_domains": self.best_domains,
            "has_meaningful_data": self.has_meaningful_data,
            "is_well_calibrated": self.is_well_calibrated,
            "updated_at": self.updated_at.isoformat(),
            "data_sources": self.data_sources,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCV:
        """Create CV from dictionary representation."""
        reliability_data = data.get("reliability", {})
        reliability = ReliabilityMetrics(
            success_rate=reliability_data.get("success_rate", 0.0),
            failure_rate=reliability_data.get("failure_rate", 0.0),
            timeout_rate=reliability_data.get("timeout_rate", 0.0),
            total_calls=reliability_data.get("total_calls", 0),
            avg_latency_ms=reliability_data.get("avg_latency_ms", 0.0),
            p50_latency_ms=reliability_data.get("p50_latency_ms", 0.0),
            p99_latency_ms=reliability_data.get("p99_latency_ms", 0.0),
        )

        domain_performance = {}
        for domain, perf_data in data.get("domain_performance", {}).items():
            domain_performance[domain] = DomainPerformance(
                domain=domain,
                elo=perf_data.get("elo", 1000.0),
                win_rate=perf_data.get("win_rate", 0.0),
                debates_count=perf_data.get("debates_count", 0),
                calibration_accuracy=perf_data.get("calibration_accuracy", 0.0),
                brier_score=perf_data.get("brier_score", 1.0),
            )

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()

        return cls(
            agent_id=data["agent_id"],
            model_name=data.get("model_name", ""),
            overall_elo=data.get("overall_elo", 1000.0),
            overall_win_rate=data.get("overall_win_rate", 0.0),
            total_debates=data.get("total_debates", 0),
            calibration_accuracy=data.get("calibration_accuracy", 0.0),
            brier_score=data.get("brier_score", 1.0),
            expected_calibration_error=data.get("expected_calibration_error", 1.0),
            calibration_bias=data.get("calibration_bias", "unknown"),
            reliability=reliability,
            domain_performance=domain_performance,
            learning_category=data.get("learning_category", "unknown"),
            elo_gain_rate=data.get("elo_gain_rate", 0.0),
            model_capabilities=data.get("model_capabilities", []),
            learned_strengths=data.get("learned_strengths", []),
            updated_at=updated_at,
            data_sources=data.get("data_sources", []),
        )


class CVBuilder:
    """
    Builder for constructing AgentCV from data sources.

    Aggregates data from:
    - EloSystem for ratings and match history
    - CalibrationTracker for prediction accuracy
    - AgentPerformanceMonitor for reliability stats

    Example:
        builder = CVBuilder(elo_system=elo, calibration_tracker=tracker)
        cv = builder.build_cv("claude-opus")
    """

    def __init__(
        self,
        elo_system: EloSystem | None = None,
        calibration_tracker: CalibrationTracker | None = None,
        performance_monitor: Any | None = None,
    ):
        self.elo_system = elo_system
        self.calibration_tracker = calibration_tracker
        self.performance_monitor = performance_monitor

    def build_cv(self, agent_id: str) -> AgentCV:
        """
        Build a complete CV for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Populated AgentCV instance
        """
        cv = AgentCV(agent_id=agent_id)
        data_sources = []

        # Gather ELO data
        if self.elo_system:
            self._populate_from_elo(cv)
            data_sources.append("elo")

        # Gather calibration data
        if self.calibration_tracker:
            self._populate_from_calibration(cv)
            data_sources.append("calibration")

        # Gather performance data
        if self.performance_monitor:
            self._populate_from_performance(cv)
            data_sources.append("performance")

        cv.data_sources = data_sources
        cv.updated_at = datetime.now()

        return cv

    def _populate_from_elo(self, cv: AgentCV) -> None:
        """Populate CV with ELO system data."""
        elo_system = self.elo_system
        if elo_system is None:
            return
        try:
            rating = elo_system.get_rating(cv.agent_id)

            cv.overall_elo = rating.elo
            cv.overall_win_rate = rating.win_rate
            cv.total_debates = rating.debates_count

            # Extract domain performance
            if rating.domain_elos:
                for domain, elo in rating.domain_elos.items():
                    cv.domain_performance[domain] = DomainPerformance(
                        domain=domain,
                        elo=elo,
                    )

            # Get learning efficiency
            try:
                efficiency = elo_system.get_learning_efficiency(cv.agent_id)
                cv.learning_category = efficiency.get("learning_category", "unknown")
                cv.elo_gain_rate = efficiency.get("elo_gain_rate", 0.0)
            except (KeyError, AttributeError, TypeError) as e:
                logger.debug("Learning efficiency lookup failed for %s: %s", cv.agent_id, e)

        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.warning("ELO data lookup failed for %s: %s", cv.agent_id, e)

    def _populate_from_calibration(self, cv: AgentCV) -> None:
        """Populate CV with calibration data."""
        calibration_tracker = self.calibration_tracker
        if calibration_tracker is None:
            return
        try:
            summary = calibration_tracker.get_calibration_summary(cv.agent_id)

            cv.calibration_accuracy = summary.accuracy
            cv.brier_score = summary.brier_score
            cv.expected_calibration_error = summary.ece
            cv.calibration_bias = summary.bias_direction

            # Get domain-specific calibration
            try:
                domain_breakdown = calibration_tracker.get_domain_breakdown(cv.agent_id)
                for domain, domain_summary in domain_breakdown.items():
                    if domain in cv.domain_performance:
                        cv.domain_performance[domain].calibration_accuracy = domain_summary.accuracy
                        cv.domain_performance[domain].brier_score = domain_summary.brier_score
                    else:
                        cv.domain_performance[domain] = DomainPerformance(
                            domain=domain,
                            calibration_accuracy=domain_summary.accuracy,
                            brier_score=domain_summary.brier_score,
                        )
            except (KeyError, AttributeError, TypeError) as e:
                logger.debug("Domain calibration lookup failed for %s: %s", cv.agent_id, e)

        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.warning("Calibration data lookup failed for %s: %s", cv.agent_id, e)

    def _populate_from_performance(self, cv: AgentCV) -> None:
        """Populate CV with performance monitor data."""
        performance_monitor = self.performance_monitor
        if performance_monitor is None:
            return
        try:
            if hasattr(performance_monitor, "agent_stats"):
                stats = performance_monitor.agent_stats.get(cv.agent_id)
                if stats:
                    cv.reliability = ReliabilityMetrics(
                        success_rate=stats.success_rate / 100,  # Convert from %
                        failure_rate=(100 - stats.success_rate) / 100,
                        timeout_rate=stats.timeout_rate / 100,
                        total_calls=stats.total_calls,
                        avg_latency_ms=stats.avg_duration_ms,
                        p50_latency_ms=stats.avg_duration_ms,  # Approximation
                        p99_latency_ms=stats.max_duration_ms,  # Approximation
                    )
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning("Performance data lookup failed for %s: %s", cv.agent_id, e)

    def build_cvs_batch(self, agent_ids: list[str]) -> dict[str, AgentCV]:
        """
        Build CVs for multiple agents efficiently.

        Uses batch queries where possible to reduce database calls.

        Args:
            agent_ids: List of agent identifiers

        Returns:
            Dict mapping agent_id to AgentCV
        """
        cvs = {}

        # Batch fetch ELO ratings
        elo_ratings = {}
        if self.elo_system:
            try:
                elo_ratings = self.elo_system.get_ratings_batch(agent_ids)
            except (KeyError, AttributeError, TypeError, ValueError) as e:
                logger.warning("Batch ELO lookup failed: %s", e)

        # Build individual CVs with pre-fetched data
        for agent_id in agent_ids:
            cv = AgentCV(agent_id=agent_id)
            data_sources = []

            # Use pre-fetched ELO data
            if agent_id in elo_ratings:
                rating = elo_ratings[agent_id]
                cv.overall_elo = rating.elo
                cv.overall_win_rate = rating.win_rate
                cv.total_debates = rating.debates_count
                if rating.domain_elos:
                    for domain, elo in rating.domain_elos.items():
                        cv.domain_performance[domain] = DomainPerformance(
                            domain=domain,
                            elo=elo,
                        )
                data_sources.append("elo")

            # Calibration (individual calls for now)
            if self.calibration_tracker:
                self._populate_from_calibration(cv)
                data_sources.append("calibration")

            # Performance
            if self.performance_monitor:
                self._populate_from_performance(cv)
                data_sources.append("performance")

            cv.data_sources = data_sources
            cv.updated_at = datetime.now()
            cvs[agent_id] = cv

        return cvs


# Singleton builder instance
_cv_builder: CVBuilder | None = None


def get_cv_builder() -> CVBuilder:
    """Get the global CVBuilder singleton instance.

    Creates it lazily with available data sources.
    """
    global _cv_builder
    if _cv_builder is None:
        # Try to get data sources
        elo_system = None
        calibration_tracker = None

        try:
            from aragora.ranking.elo import get_elo_store

            elo_system = get_elo_store()
        except ImportError:
            logger.debug("ELO system not available for CV builder")
        except Exception as e:
            logger.warning("Failed to initialise ELO system for CV builder: %s", e)

        try:
            from aragora.agents.calibration import CalibrationTracker

            calibration_tracker = CalibrationTracker()
        except ImportError:
            logger.debug("CalibrationTracker not available for CV builder")
        except Exception as e:
            logger.warning("Failed to initialise CalibrationTracker for CV builder: %s", e)

        _cv_builder = CVBuilder(
            elo_system=elo_system,
            calibration_tracker=calibration_tracker,
        )

    return _cv_builder
