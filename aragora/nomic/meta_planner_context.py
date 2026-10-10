"""Planning-context enrichment for ``MetaPlanner``.

``MetaPlanner`` (``aragora.nomic.meta_planner``) inherits these methods: before the
planning debate they add a codebase metrics snapshot (size and lint) to the
``PlanningContext``, plus learnings from similar past cycles in the Knowledge Mound,
recent pipeline outcomes, outcome-tracker regressions, agent calibration records and
strategic-memory findings. Import the planner from ``aragora.nomic.meta_planner``.
"""

from __future__ import annotations

import logging

from aragora.nomic.meta_planner_models import (
    HistoricalLearning,
    MetaPlannerConfig,
    PlanningContext,
)
from aragora.nomic.types import Track

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.meta_planner" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.meta_planner")


def _scope_summary(
    affected_files: list[str],
    expected_tests: list[str],
) -> str:
    """Render compact pipeline scope context for planning feedback."""
    parts: list[str] = []
    if affected_files:
        parts.append(f"files: {', '.join(affected_files[:3])}")
    if expected_tests:
        parts.append(f"tests: {'; '.join(expected_tests[:2])}")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"


class MetaPlannerContextMixin:
    """Metrics and past-cycle context enrichment inherited by ``MetaPlanner``."""

    config: MetaPlannerConfig

    def _enrich_context_with_metrics(self, context: PlanningContext) -> PlanningContext:
        """Enrich planning context with codebase metrics.

        Instantiates MetricsCollector, runs a synchronous collection of test/lint/size
        metrics, and injects the snapshot into PlanningContext.metric_snapshot so the
        debate topic can include hard numbers.

        Args:
            context: Existing planning context

        Returns:
            Enriched PlanningContext with metric_snapshot populated
        """
        try:
            from aragora.nomic.metrics_collector import MetricsCollector, MetricsCollectorConfig

            config = MetricsCollectorConfig(
                test_args=["-x", "-q", "--tb=no", "--timeout=60"],
                test_timeout=120,
            )
            collector = MetricsCollector(config)

            # Synchronous collection of size + lint (skip tests for speed in planning)
            from aragora.nomic.metrics_collector import MetricSnapshot
            import time

            snapshot = MetricSnapshot(timestamp=time.time())
            try:
                collector._collect_size_metrics(snapshot, None)
            except (OSError, ValueError) as e:
                logger.debug("metrics_size_collection_failed: %s", e)
            try:
                collector._collect_lint_metrics(snapshot, None)
            except (OSError, ValueError, Exception) as e:  # noqa: BLE001
                logger.debug("metrics_lint_collection_failed: %s", e)

            context.metric_snapshot = snapshot.to_dict()

            # Inject notable issues into recent_issues for debate visibility
            if snapshot.lint_errors > 0:
                context.recent_issues.append(
                    f"[metrics] {snapshot.lint_errors} lint errors detected"
                )
            if snapshot.tests_failed > 0:
                context.recent_issues.append(
                    f"[metrics] {snapshot.tests_failed} test failures detected"
                )

            logger.info(
                "metrics_enrichment_complete files=%d lines=%d lint_errors=%d",
                snapshot.files_count,
                snapshot.total_lines,
                snapshot.lint_errors,
            )

        except ImportError:
            logger.debug("MetricsCollector not available, skipping metrics enrichment")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to enrich context with metrics: %s", e)

        return context

    async def _enrich_context_with_history(
        self,
        objective: str,
        tracks: list[Track],
        context: PlanningContext,
    ) -> PlanningContext:
        """Enrich planning context with learnings from past cycles.

        Queries the Knowledge Mound for similar past cycles and extracts
        relevant learnings to inform the current planning session.

        Args:
            objective: Current planning objective
            tracks: Available tracks
            context: Existing planning context

        Returns:
            Enriched PlanningContext with historical learnings
        """
        try:
            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                get_nomic_cycle_adapter,
            )

            adapter = get_nomic_cycle_adapter()
            track_names = [t.value for t in tracks]

            similar_cycles = await adapter.find_similar_cycles(
                objective=objective,
                tracks=track_names,
                limit=self.config.max_similar_cycles,
                min_similarity=self.config.min_cycle_similarity,
            )

            if similar_cycles:
                logger.info(
                    "cross_cycle_learning found=%s cycles for objective=%s",
                    len(similar_cycles),
                    objective[:50],
                )

            for cycle in similar_cycles:
                # Add what worked
                for success in cycle.what_worked:
                    context.past_successes_to_build_on.append(f"[{cycle.objective[:30]}] {success}")
                    context.historical_learnings.append(
                        HistoricalLearning(
                            cycle_id=cycle.cycle_id,
                            objective=cycle.objective,
                            was_success=True,
                            lesson=success,
                            relevance=cycle.similarity,
                        )
                    )

                # Add what failed (important to avoid!)
                for failure in cycle.what_failed:
                    context.past_failures_to_avoid.append(f"[{cycle.objective[:30]}] {failure}")
                    context.historical_learnings.append(
                        HistoricalLearning(
                            cycle_id=cycle.cycle_id,
                            objective=cycle.objective,
                            was_success=False,
                            lesson=failure,
                            relevance=cycle.similarity,
                        )
                    )

            # Query high-ROI goal types for smarter prioritization
            try:
                high_roi = await adapter.find_high_roi_goal_types(limit=5)
                for roi_entry in high_roi:
                    if roi_entry.get("avg_improvement_score", 0) > 0.3:
                        context.past_successes_to_build_on.append(
                            f"[high_roi] Pattern '{roi_entry['pattern']}' "
                            f"avg_improvement={roi_entry['avg_improvement_score']:.2f} "
                            f"({roi_entry['cycle_count']} cycles)"
                        )
                if high_roi:
                    logger.info("high_roi_patterns loaded=%d for planning", len(high_roi))
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.debug("High-ROI query failed: %s", e)

            # Query recurring failures to avoid
            try:
                recurring = await adapter.find_recurring_failures(min_occurrences=2, limit=5)
                for rec_failure in recurring:
                    tracks_str = ", ".join(rec_failure.get("affected_tracks", [])[:3])
                    context.past_failures_to_avoid.append(
                        f"[recurring_failure] '{rec_failure['pattern']}' "
                        f"({rec_failure['occurrences']}x"
                        f"{', tracks: ' + tracks_str if tracks_str else ''})"
                    )
                if recurring:
                    logger.info("recurring_failures loaded=%d for planning", len(recurring))
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.debug("Recurring failures query failed: %s", e)

        except ImportError:
            logger.debug("Nomic cycle adapter not available, skipping history enrichment")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to enrich context with history: %s", e)

        # Also query PlanStore for recent pipeline outcomes
        try:
            from aragora.pipeline.plan_store import get_plan_store

            store = get_plan_store()
            outcomes = store.get_recent_outcomes(limit=5) if store else []

            for outcome in outcomes or []:
                status = outcome.get("status", "unknown")
                task = outcome.get("task", "unknown task")
                exec_error = outcome.get("execution_error")
                affected_files = [
                    str(item).strip()
                    for item in outcome.get("affected_files", [])
                    if str(item).strip()
                ]
                expected_tests = [
                    str(item).strip()
                    for item in outcome.get("expected_tests", [])
                    if str(item).strip()
                ]
                scope_suffix = _scope_summary(affected_files, expected_tests)

                if affected_files:
                    change_entry = f"[pipeline:{status}] {', '.join(affected_files[:4])}"
                    if change_entry not in context.recent_changes:
                        context.recent_changes.append(change_entry)

                if status in ("failed", "rejected") or exec_error:
                    for test_cmd in expected_tests[:3]:
                        failure_hint = f"[pipeline:{status}] {test_cmd}"
                        if failure_hint not in context.test_failures:
                            context.test_failures.append(failure_hint)

                if status in ("completed",) and not exec_error:
                    context.past_successes_to_build_on.append(
                        f"[pipeline] {task[:60]}{scope_suffix}"
                    )
                elif status in ("failed", "rejected") or exec_error:
                    error_msg = ""
                    if exec_error and isinstance(exec_error, dict):
                        error_msg = f": {exec_error.get('message', '')[:80]}"
                    context.past_failures_to_avoid.append(
                        f"[pipeline:{status}] {task[:60]}{error_msg}{scope_suffix}"
                    )

            if outcomes:
                logger.info("pipeline_feedback loaded=%s outcomes for planning", len(outcomes))
        except ImportError:
            logger.debug("PlanStore not available, skipping pipeline feedback")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to load pipeline outcomes: %s", e)

        # Outcome tracker feedback: inject regression data from past cycles
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            regressions = NomicOutcomeTracker.get_regression_history(limit=5)
            for reg in regressions:
                regressed = ", ".join(reg["regressed_metrics"])
                context.past_failures_to_avoid.append(
                    f"[outcome_regression] Cycle {reg['cycle_id'][:8]} regressed: {regressed} "
                    f"(recommendation: {reg['recommendation']})"
                )
            if regressions:
                logger.info("outcome_feedback loaded=%d regressions for planning", len(regressions))
        except ImportError:
            logger.debug("OutcomeTracker not available, skipping regression feedback")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to load outcome regressions: %s", e)

        # --- Calibration data enrichment ---
        try:
            from aragora.ranking.elo import get_elo_store
            from aragora.agents.calibration import CalibrationTracker

            elo = get_elo_store()
            calibration = CalibrationTracker()

            # Get agents ranked by calibration quality
            cal_leaders = calibration.get_leaderboard(metric="brier", limit=5)
            if cal_leaders:
                well_calibrated = [name for name, score in cal_leaders if score < 0.25]
                if well_calibrated:
                    context.past_successes_to_build_on.append(
                        f"[calibration] Well-calibrated agents: "
                        f"{', '.join(well_calibrated[:3])} (Brier < 0.25)"
                    )

            # Get domain-specific performance for relevant tracks
            all_ratings = elo.get_all_ratings()
            underperformers = []
            for rating in all_ratings[:10]:  # Top 10 agents by ELO
                if rating.calibration_total >= 5:
                    brier = rating.calibration_brier_score
                    if brier > 0.35:
                        underperformers.append(f"{rating.agent_name} (Brier={brier:.2f})")

            if underperformers:
                context.past_failures_to_avoid.append(
                    f"[calibration] Overconfident agents needing "
                    f"improvement: {', '.join(underperformers[:3])}"
                )

            logger.info(
                "calibration_enrichment leaders=%d underperformers=%d",
                len(cal_leaders) if cal_leaders else 0,
                len(underperformers),
            )
        except ImportError:
            logger.debug("Calibration subsystems not available")
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to enrich with calibration data: %s", e)

        # Strategic memory: query past strategic assessments for this objective
        try:
            from aragora.nomic.strategic_memory import StrategicMemoryStore

            sm_store = StrategicMemoryStore()
            past_assessments = sm_store.get_for_objective(objective, limit=3)
            if past_assessments:
                for assessment in past_assessments:
                    for finding in assessment.findings[:3]:
                        context.recent_issues.append(
                            f"[strategic:{finding.category}] {finding.description[:100]}"
                        )
                logger.info(
                    "strategic_memory_enrichment assessments=%d for objective=%s",
                    len(past_assessments),
                    objective[:50],
                )

            # Boost recurring findings
            recurring_findings = sm_store.get_recurring_findings(min_occurrences=2)
            for finding in recurring_findings[:5]:
                context.recent_issues.append(
                    f"[recurring:{finding.category}] {finding.description[:100]}"
                )
            if recurring_findings:
                logger.info("strategic_memory_recurring count=%d", len(recurring_findings))
        except ImportError:
            logger.debug("Strategic memory not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Strategic memory query failed: %s", exc)

        return context
