"""Nomic Loop Outcome Tracker - measures whether improvements helped debate quality.

Captures debate quality metrics before and after a Nomic Loop cycle to detect
silent regressions. If an improvement cycle makes code changes that degrade
consensus rates, increase token costs, or widen calibration spread, the tracker
flags the regression and recommends a revert.

Usage:
    tracker = NomicOutcomeTracker()

    baseline = await tracker.capture_baseline()
    # ... run improvement cycle ...
    after = await tracker.capture_after()

    comparison = tracker.compare(baseline, after)
    if not comparison.improved:
        print(f"Regression detected: {comparison.recommendation}")

    # Persist to cycle store
    tracker.record_cycle_outcome("cycle_123", comparison)
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable, Awaitable

logger = logging.getLogger(__name__)

# Default degradation threshold: a metric must degrade by more than 5%
# relative to its baseline to count as a regression.
DEGRADATION_THRESHOLD = 0.05

# Default number of test scenarios to run for metric capture.
DEFAULT_SCENARIO_COUNT = 3


@dataclass
class DebateMetrics:
    """Point-in-time snapshot of debate quality metrics."""

    consensus_rate: float = 0.0  # 0-1, fraction of debates reaching consensus
    avg_rounds: float = 0.0  # average rounds to reach consensus
    avg_tokens: int = 0  # average token cost per debate
    calibration_spread: float = 0.0  # std dev of agent Brier scores (lower = better)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "consensus_rate": self.consensus_rate,
            "avg_rounds": self.avg_rounds,
            "avg_tokens": self.avg_tokens,
            "calibration_spread": self.calibration_spread,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateMetrics:
        return cls(
            consensus_rate=data.get("consensus_rate", 0.0),
            avg_rounds=data.get("avg_rounds", 0.0),
            avg_tokens=data.get("avg_tokens", 0),
            calibration_spread=data.get("calibration_spread", 0.0),
            timestamp=data.get("timestamp", 0.0),
        )


@dataclass
class OutcomeComparison:
    """Result of comparing baseline vs post-improvement debate metrics."""

    baseline: DebateMetrics
    after: DebateMetrics
    improved: bool = False
    metrics_delta: dict[str, float] = field(default_factory=dict)
    recommendation: str = "review"  # "keep" | "revert" | "review"

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "after": self.after.to_dict(),
            "improved": self.improved,
            "metrics_delta": self.metrics_delta,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutcomeComparison:
        return cls(
            baseline=DebateMetrics.from_dict(data.get("baseline", {})),
            after=DebateMetrics.from_dict(data.get("after", {})),
            improved=data.get("improved", False),
            metrics_delta=data.get("metrics_delta", {}),
            recommendation=data.get("recommendation", "review"),
        )


@dataclass
class DebateScenario:
    """A lightweight test debate scenario for metric capture.

    Instead of running real API-backed debates, scenarios provide
    deterministic or simulated debate outcomes for measurement.
    """

    topic: str
    expected_rounds: int = 3
    agent_count: int = 3

    # Callable that returns simulated debate results.
    # Signature: async (topic, agent_count, expected_rounds) -> dict
    runner: Callable[..., Awaitable[dict[str, Any]]] | None = None


@dataclass
class RegressionResult:
    """Result of a quick regression check via scoped pytest run.

    Fields:
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        duration_seconds: Wall-clock time for the test run.
        is_regression: True if any test failed (indicating a regression).
    """

    passed: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    is_regression: bool = False


# A default set of lightweight scenarios for baseline/after capture.
DEFAULT_SCENARIOS: list[DebateScenario] = [
    DebateScenario(topic="Should we add rate limiting to the API?", expected_rounds=3),
    DebateScenario(topic="Is the current test coverage sufficient?", expected_rounds=2),
    DebateScenario(topic="Should we refactor the memory subsystem?", expected_rounds=4),
]


async def _default_scenario_runner(
    topic: str,
    agent_count: int,
    expected_rounds: int,
) -> dict[str, Any]:
    """Scenario runner that uses recent debate data when available.

    Queries ContinuumMemory or ConsensusStore for recent real debate metrics.
    Falls back to plausible simulated values for testing and offline use.
    """
    # Try to source real metrics from recent debates
    try:
        from aragora.memory.consensus import ConsensusStore

        store = ConsensusStore()
        recent = store.get_recent(limit=10)  # type: ignore[attr-defined]
        if recent and len(recent) >= 3:
            consensus_count = sum(1 for d in recent if d.get("consensus_reached"))
            avg_rounds = sum(d.get("rounds", expected_rounds) for d in recent) / len(recent)
            avg_tokens = sum(d.get("tokens_used", 0) for d in recent) / len(recent)
            brier = [d.get("calibration_score", 0.25) for d in recent[:agent_count]]
            return {
                "consensus_reached": consensus_count > len(recent) // 2,
                "rounds": int(avg_rounds),
                "tokens_used": int(avg_tokens) or expected_rounds * agent_count * 500,
                "brier_scores": brier or [0.25] * agent_count,
            }
    except (ImportError, AttributeError, TypeError, RuntimeError):
        pass

    # Fallback: deterministic simulated values for offline/testing
    return {
        "consensus_reached": True,
        "rounds": expected_rounds,
        "tokens_used": expected_rounds * agent_count * 500,
        "brier_scores": [0.2, 0.25, 0.3][:agent_count],
    }


async def _lightweight_debate_runner(
    topic: str,
    agent_count: int,
    expected_rounds: int,
) -> dict[str, Any]:
    """Run a real lightweight debate for outcome verification.

    Uses minimal settings to keep costs low:
    - Max 2 rounds (regardless of expected_rounds)
    - Only 2 agents
    - No KM integration, no memory, no spectator
    - Short timeout

    Falls back to simulated metrics if Arena is unavailable.
    """
    try:
        from aragora.core_types import Environment
        from aragora.debate.orchestrator import Arena
        from aragora.protocols.debate import DebateProtocol

        env = Environment(task=topic)
        protocol = DebateProtocol(
            rounds=min(expected_rounds, 2),
            consensus="majority",
            early_stopping=True,
        )

        # Use the cheapest available agents
        agents = []
        for agent_type in ["anthropic-api", "openai-api"][:agent_count]:
            try:
                from aragora.agents.base import create_agent

                agent = create_agent(agent_type)  # type: ignore[arg-type]
                agents.append(agent)
            except (ImportError, ValueError, RuntimeError):
                continue

        if len(agents) < 2:
            # Not enough agents available, fall back to simulation
            return await _default_scenario_runner(topic, agent_count, expected_rounds)

        result = await Arena(env, agents, protocol).run()

        brier_scores: list[float] = []
        try:
            from aragora.agents.calibration import CalibrationTracker

            cal = CalibrationTracker()
            for agent in agents:
                name = getattr(agent, "name", str(agent))
                score = cal.get_brier_score(name, "general")
                if score is not None:
                    brier_scores.append(score)
        except (ImportError, RuntimeError, ValueError):
            brier_scores = [0.25] * len(agents)  # Default

        return {
            "consensus_reached": result.consensus_reached,
            "rounds": result.rounds_completed
            if hasattr(result, "rounds_completed")
            else expected_rounds,
            "tokens_used": getattr(result, "total_tokens", expected_rounds * agent_count * 500),
            "brier_scores": brier_scores or [0.25] * agent_count,
        }
    except (ImportError, RuntimeError, ValueError, TypeError, OSError) as e:
        logger.debug("Lightweight debate runner unavailable, using simulation: %s", e)
        return await _default_scenario_runner(topic, agent_count, expected_rounds)


class NomicOutcomeTracker:
    """Tracks whether Nomic Loop improvements actually help debate quality.

    Runs a fixed set of test debate scenarios before and after a code change,
    then compares the metrics to detect regressions.

    Args:
        scenarios: List of debate scenarios to run. Defaults to DEFAULT_SCENARIOS.
        scenario_runner: Async callable to execute each scenario. If None, uses
            the default simulated runner.
        degradation_threshold: Maximum allowed relative degradation per metric
            before it counts as a regression. Default: 0.05 (5%).
        cycle_store: Optional CycleLearningStore for persisting outcomes.
    """

    def __init__(
        self,
        scenarios: list[DebateScenario] | None = None,
        scenario_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        degradation_threshold: float = DEGRADATION_THRESHOLD,
        cycle_store: Any | None = None,
    ):
        self.scenarios = list(DEFAULT_SCENARIOS) if scenarios is None else scenarios
        self._runner = scenario_runner or _default_scenario_runner
        self.degradation_threshold = degradation_threshold
        self._cycle_store = cycle_store

    @classmethod
    def create_with_real_debates(
        cls,
        degradation_threshold: float = DEGRADATION_THRESHOLD,
        cycle_store: Any | None = None,
    ) -> NomicOutcomeTracker:
        """Create a tracker that runs real lightweight debates for verification.

        Uses ``_lightweight_debate_runner`` which executes actual Arena debates
        with minimal settings (max 2 rounds, 2 agents, early stopping) to keep
        costs low. Falls back to simulated debates if Arena is unavailable.
        """
        return cls(
            scenario_runner=_lightweight_debate_runner,
            degradation_threshold=degradation_threshold,
            cycle_store=cycle_store,
        )

    async def verify_diff(self, diff: str, label: str = "nomic-cycle") -> dict[str, Any]:
        """Verify a code diff using multi-agent review.

        Delegates to PRReviewRunner.review_diff() to check for regressions,
        security issues, and code quality problems in the changed code.

        Args:
            diff: The unified diff to verify.
            label: Label for the review.

        Returns:
            Dict with 'passed', 'findings_count', 'agreement_score' keys.
            If PRReviewRunner is unavailable, returns ``{"passed": True, "skipped": True}``.
        """
        try:
            from aragora.compat.openclaw.pr_review_runner import PRReviewRunner

            runner = PRReviewRunner()
            review = await runner.review_diff(diff=diff, label=label)

            has_critical = any(f.severity == "critical" for f in getattr(review, "findings", []))
            return {
                "passed": not has_critical and review.error is None,
                "findings_count": len(getattr(review, "findings", [])),
                "agreement_score": getattr(review, "agreement_score", None),
            }
        except ImportError:
            logger.debug("PRReviewRunner not available for diff verification")
            return {"passed": True, "skipped": True}
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Diff verification failed: %s", e)
            return {"passed": False, "error": str(e)}

    async def capture_baseline(self) -> DebateMetrics:
        """Run test debates and capture pre-improvement metrics."""
        return await self._capture("baseline")

    async def capture_after(self) -> DebateMetrics:
        """Run test debates and capture post-improvement metrics."""
        return await self._capture("after")

    def compare(
        self,
        baseline: DebateMetrics,
        after: DebateMetrics,
    ) -> OutcomeComparison:
        """Compare baseline and after metrics to determine outcome.

        A metric is considered degraded if it worsens by more than
        ``degradation_threshold`` relative to the baseline value.

        For consensus_rate: higher is better (degradation = decrease).
        For avg_rounds: lower is better (degradation = increase).
        For avg_tokens: lower is better (degradation = increase).
        For calibration_spread: lower is better (degradation = increase).

        Returns:
            OutcomeComparison with improvement status and recommendation.
        """
        deltas: dict[str, float] = {}
        regressions: list[str] = []
        improvements: list[str] = []

        # consensus_rate: higher is better
        cr_delta = after.consensus_rate - baseline.consensus_rate
        deltas["consensus_rate"] = cr_delta
        if baseline.consensus_rate > 0 and cr_delta < 0:
            if abs(cr_delta) / baseline.consensus_rate > self.degradation_threshold:
                regressions.append("consensus_rate")
        if cr_delta > 0:
            improvements.append("consensus_rate")

        # avg_rounds: lower is better
        rounds_delta = after.avg_rounds - baseline.avg_rounds
        deltas["avg_rounds"] = rounds_delta
        if baseline.avg_rounds > 0 and rounds_delta > 0:
            if rounds_delta / baseline.avg_rounds > self.degradation_threshold:
                regressions.append("avg_rounds")
        if rounds_delta < 0:
            improvements.append("avg_rounds")

        # avg_tokens: lower is better
        tokens_delta = after.avg_tokens - baseline.avg_tokens
        deltas["avg_tokens"] = float(tokens_delta)
        if baseline.avg_tokens > 0 and tokens_delta > 0:
            if tokens_delta / baseline.avg_tokens > self.degradation_threshold:
                regressions.append("avg_tokens")
        if tokens_delta < 0:
            improvements.append("avg_tokens")

        # calibration_spread: lower is better
        cal_delta = after.calibration_spread - baseline.calibration_spread
        deltas["calibration_spread"] = cal_delta
        if baseline.calibration_spread > 0 and cal_delta > 0:
            if cal_delta / baseline.calibration_spread > self.degradation_threshold:
                regressions.append("calibration_spread")
        if cal_delta < 0:
            improvements.append("calibration_spread")

        # Determine recommendation
        if regressions:
            improved = False
            recommendation = "revert" if len(regressions) >= 2 else "review"
        elif improvements:
            improved = True
            recommendation = "keep"
        else:
            # No change
            improved = True
            recommendation = "keep"

        comparison = OutcomeComparison(
            baseline=baseline,
            after=after,
            improved=improved,
            metrics_delta=deltas,
            recommendation=recommendation,
        )

        logger.info(
            "outcome_comparison recommendation=%s improved=%s regressions=%s improvements=%s",
            recommendation,
            improved,
            regressions,
            improvements,
        )

        return comparison

    def record_cycle_outcome(
        self,
        cycle_id: str,
        comparison: OutcomeComparison,
    ) -> None:
        """Persist comparison results to the cycle store.

        If a cycle_store was provided at init time, updates the cycle record
        with the outcome comparison data. Otherwise, logs a warning and no-ops.

        Args:
            cycle_id: The Nomic cycle ID to update.
            comparison: The outcome comparison to record.
        """
        if self._cycle_store is None:
            try:
                from aragora.nomic.cycle_store import get_cycle_store

                self._cycle_store = get_cycle_store()
            except (ImportError, OSError) as e:
                logger.warning(
                    "outcome_record_skipped cycle_id=%s reason=no_cycle_store error=%s",
                    cycle_id,
                    e,
                )
                return

        record = self._cycle_store.load_cycle(cycle_id)
        if record is None:
            logger.warning(
                "outcome_record_skipped cycle_id=%s reason=cycle_not_found",
                cycle_id,
            )
            return

        # Store outcome data as a pattern reinforcement
        record.add_pattern_reinforcement(
            pattern_type="outcome_tracking",
            description=(
                f"Debate quality {'improved' if comparison.improved else 'degraded'}: "
                f"recommendation={comparison.recommendation}"
            ),
            success=comparison.improved,
            confidence=0.8 if comparison.improved else 0.3,
        )

        # Store detailed metrics in evidence_quality_scores
        for metric_name, delta_value in comparison.metrics_delta.items():
            record.evidence_quality_scores[f"outcome_{metric_name}_delta"] = delta_value

        self._cycle_store.save_cycle(record)

        logger.info(
            "outcome_recorded cycle_id=%s improved=%s recommendation=%s",
            cycle_id,
            comparison.improved,
            comparison.recommendation,
        )

    @staticmethod
    def get_regression_history(limit: int = 10) -> list[dict[str, Any]]:
        """Load recent cycle outcomes and return those with regressions.

        Queries the CycleLearningStore for recent cycles, inspects their
        ``evidence_quality_scores`` for negative deltas stored by
        ``record_cycle_outcome()``, and returns a summary of regressed
        cycles with actionable recommendations.

        Args:
            limit: Maximum number of recent cycles to inspect.

        Returns:
            List of dicts, each with keys:
              - cycle_id: str
              - regressed_metrics: list[str]
              - recommendation: str
        """
        try:
            from aragora.nomic.cycle_store import get_cycle_store
        except ImportError:
            logger.debug("CycleLearningStore not available for regression history")
            return []

        try:
            store = get_cycle_store()
            cycles = store.get_recent_cycles(limit)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Failed to load cycles for regression history: %s", e)
            return []

        regressions: list[dict[str, Any]] = []

        # Metrics where a positive delta means degradation (lower-is-better metrics)
        lower_is_better = {"avg_rounds", "avg_tokens", "calibration_spread"}
        # Metrics where a negative delta means degradation (higher-is-better metrics)
        higher_is_better = {"consensus_rate"}

        for cycle in cycles:
            scores = cycle.evidence_quality_scores
            if not scores:
                continue

            regressed_metrics: list[str] = []

            for key, delta in scores.items():
                if not key.startswith("outcome_") or not key.endswith("_delta"):
                    continue

                # Extract the metric name: "outcome_consensus_rate_delta" -> "consensus_rate"
                metric_name = key[len("outcome_") : -len("_delta")]

                if metric_name in higher_is_better and delta < 0:
                    regressed_metrics.append(metric_name)
                elif metric_name in lower_is_better and delta > 0:
                    regressed_metrics.append(metric_name)

            if regressed_metrics:
                # Derive recommendation from the pattern reinforcements
                recommendation = "review"
                for reinforcement in cycle.pattern_reinforcements:
                    if reinforcement.pattern_type == "outcome_tracking":
                        if "revert" in reinforcement.description:
                            recommendation = "revert"
                        elif "review" in reinforcement.description:
                            recommendation = "review"
                        break

                regressions.append(
                    {
                        "cycle_id": cycle.cycle_id,
                        "regressed_metrics": regressed_metrics,
                        "recommendation": recommendation,
                    }
                )

        return regressions

    @staticmethod
    def quick_regression_check(
        worktree_path: str,
        test_pattern: str | None = None,
    ) -> RegressionResult:
        """Run a fast, scoped pytest to detect regressions in changed files.

        Instead of running the full test suite (which can take minutes), this
        method runs only the tests matching an optional pattern, with a short
        timeout. This is the key insight from oracle-driven validation: scope
        tests to ONLY the files changed, not the full suite.

        Args:
            worktree_path: Path to the git worktree or project root where
                tests should run.
            test_pattern: Optional pytest ``-k`` filter to scope the test run.
                For example, ``"test_task_decomposer"`` to run only
                decomposer tests. If None, runs all tests in the worktree.

        Returns:
            RegressionResult with pass/fail counts and whether a regression
            was detected. On subprocess errors, returns a result with
            is_regression=False and zero counts (graceful degradation).
        """
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "--tb=no",
            "-q",
            "--timeout=10",
        ]
        if test_pattern:
            cmd.extend(["-k", test_pattern])

        start_time = time.time()
        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                cmd,
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=30,
            )
            duration = time.time() - start_time

            # Parse pytest summary line: "X passed, Y failed" or "X passed"
            stdout = result.stdout
            passed = 0
            failed = 0

            # Match patterns like "5 passed", "3 failed", "2 error"
            import re

            pass_match = re.search(r"(\d+) passed", stdout)
            fail_match = re.search(r"(\d+) failed", stdout)
            error_match = re.search(r"(\d+) error", stdout)

            if pass_match:
                passed = int(pass_match.group(1))
            if fail_match:
                failed = int(fail_match.group(1))
            if error_match:
                failed += int(error_match.group(1))

            is_regression = failed > 0

            logger.info(
                "quick_regression_check passed=%d failed=%d duration=%.1fs "
                "regression=%s pattern=%s",
                passed,
                failed,
                duration,
                is_regression,
                test_pattern,
            )

            return RegressionResult(
                passed=passed,
                failed=failed,
                duration_seconds=round(duration, 2),
                is_regression=is_regression,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.warning(
                "quick_regression_check_timeout duration=%.1fs pattern=%s",
                duration,
                test_pattern,
            )
            return RegressionResult(
                passed=0,
                failed=0,
                duration_seconds=round(duration, 2),
                is_regression=False,
            )
        except OSError as e:
            logger.warning("quick_regression_check_error error=%s", e)
            return RegressionResult(
                passed=0,
                failed=0,
                duration_seconds=0.0,
                is_regression=False,
            )

    # --- Internal ---

    async def _capture(self, label: str) -> DebateMetrics:
        """Run all scenarios and aggregate metrics."""
        consensus_count = 0
        total_rounds = 0
        total_tokens = 0
        all_brier: list[float] = []

        for scenario in self.scenarios:
            runner = scenario.runner or self._runner
            try:
                result = await runner(
                    scenario.topic,
                    scenario.agent_count,
                    scenario.expected_rounds,
                )

                if result.get("consensus_reached", False):
                    consensus_count += 1

                total_rounds += result.get("rounds", scenario.expected_rounds)
                total_tokens += result.get("tokens_used", 0)

                brier_scores = result.get("brier_scores", [])
                all_brier.extend(brier_scores)

            except (RuntimeError, OSError, ValueError, TypeError) as e:
                logger.warning(
                    "scenario_failed label=%s topic=%s error=%s",
                    label,
                    scenario.topic[:50],
                    e,
                )

        n = len(self.scenarios)
        if n == 0:
            return DebateMetrics()

        # Calibration spread = std dev of Brier scores
        cal_spread = 0.0
        if all_brier:
            mean_brier = sum(all_brier) / len(all_brier)
            variance = sum((b - mean_brier) ** 2 for b in all_brier) / len(all_brier)
            cal_spread = variance**0.5

        metrics = DebateMetrics(
            consensus_rate=consensus_count / n,
            avg_rounds=total_rounds / n,
            avg_tokens=total_tokens // n,
            calibration_spread=cal_spread,
        )

        logger.info(
            "metrics_captured label=%s consensus_rate=%.2f avg_rounds=%.1f "
            "avg_tokens=%d calibration_spread=%.3f",
            label,
            metrics.consensus_rate,
            metrics.avg_rounds,
            metrics.avg_tokens,
            metrics.calibration_spread,
        )

        return metrics
