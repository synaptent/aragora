"""Goal Proposer - data-driven goal generation for the Nomic Loop.

Scores potential improvement goals from multiple signal sources:
- Test failure patterns
- Performance bottlenecks (slow cycles)
- Knowledge staleness
- Calibration drift

Usage:
    from aragora.nomic.goal_proposer import GoalProposer

    proposer = GoalProposer()
    goals = proposer.propose_goals(max_goals=5, min_confidence=0.7)
    for g in goals:
        print(f"{g.goal_text} (conf={g.confidence:.2f})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GoalCandidate:
    """A proposed improvement goal with scoring metadata."""

    goal_text: str
    confidence: float  # 0-1
    signal_source: str  # e.g. "test_failures", "slow_cycles", "staleness", "calibration"
    estimated_effort: float = 1.0  # relative effort (higher = more work)
    estimated_impact: float = 1.0  # relative impact (higher = more value)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Composite score: confidence * impact / effort.

        Effort is clamped to a minimum of 0.1 to avoid division by zero.
        """
        effort = max(self.estimated_effort, 0.1)
        return self.confidence * self.estimated_impact / effort


class GoalProposer:
    """Generate and rank improvement goals from multiple signal sources.

    Each signal source produces zero or more GoalCandidate objects.
    Candidates are ranked by composite score (confidence * impact / effort)
    and filtered by minimum confidence threshold.
    """

    def __init__(
        self,
        telemetry: Any | None = None,
        calibration_monitor: Any | None = None,
    ):
        """Initialize the goal proposer.

        Args:
            telemetry: Optional CycleTelemetryCollector for cycle data.
            calibration_monitor: Optional CalibrationDriftDetector.
        """
        self._telemetry = telemetry
        self._calibration_monitor = calibration_monitor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose_goals(
        self,
        max_goals: int = 5,
        min_confidence: float = 0.7,
    ) -> list[GoalCandidate]:
        """Collect signals, score candidates, and return ranked goals.

        Args:
            max_goals: Maximum number of goals to return.
            min_confidence: Minimum confidence threshold for inclusion.

        Returns:
            Sorted list of GoalCandidate (highest score first).
        """
        candidates: list[GoalCandidate] = []

        # Gather from all signal sources (each may fail independently)
        for source_fn in [
            self._signal_test_failures,
            self._signal_slow_cycles,
            self._signal_knowledge_staleness,
            self._signal_calibration_drift,
            self._signal_coverage_gaps,
            self._signal_lint_regressions,
        ]:
            try:
                results = source_fn()
                candidates.extend(results)
            except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                fn_name = getattr(source_fn, "__name__", repr(source_fn))
                logger.debug("goal_proposer_signal_error source=%s: %s", fn_name, e)

        # Filter by minimum confidence
        filtered = [c for c in candidates if c.confidence >= min_confidence]

        # Sort by composite score descending
        filtered.sort(key=lambda c: c.score, reverse=True)

        selected = filtered[:max_goals]
        logger.info(
            "goal_proposer_complete candidates=%d filtered=%d selected=%d",
            len(candidates),
            len(filtered),
            len(selected),
        )
        return selected

    # ------------------------------------------------------------------
    # Signal: Test Failures
    # ------------------------------------------------------------------

    def _signal_test_failures(self) -> list[GoalCandidate]:
        """Parse pytest output for recurring failure patterns.

        Reads .pytest_cache/v/cache/lastfailed and groups failures
        by module to propose fix goals.
        """
        candidates: list[GoalCandidate] = []
        try:
            import json as _json
            from pathlib import Path as _P

            lastfailed_path = _P(".pytest_cache/v/cache/lastfailed")
            if not lastfailed_path.exists():
                return candidates

            failed = _json.loads(lastfailed_path.read_text())
            if not failed:
                return candidates

            # Group failures by module
            module_failures: dict[str, list[str]] = {}
            for node_id in failed:
                parts = node_id.split("::")
                module = parts[0] if parts else node_id
                module_failures.setdefault(module, []).append(node_id)

            for module, node_ids in sorted(
                module_failures.items(), key=lambda kv: len(kv[1]), reverse=True
            ):
                count = len(node_ids)
                confidence = min(0.5 + count * 0.1, 0.99)
                candidates.append(
                    GoalCandidate(
                        goal_text=f"Fix {count} test failure(s) in {module}",
                        confidence=confidence,
                        signal_source="test_failures",
                        estimated_effort=0.5 + count * 0.2,
                        estimated_impact=1.0 + count * 0.3,
                        metadata={"module": module, "count": count, "node_ids": node_ids[:5]},
                    )
                )

        except (OSError, ValueError, _json.JSONDecodeError):
            pass

        return candidates

    # ------------------------------------------------------------------
    # Signal: Slow Cycles (performance bottlenecks)
    # ------------------------------------------------------------------

    def _signal_slow_cycles(self) -> list[GoalCandidate]:
        """Check telemetry for abnormally slow cycles and propose optimizations."""
        candidates: list[GoalCandidate] = []
        if self._telemetry is None:
            return candidates

        try:
            recent = self._telemetry.get_recent_cycles(n=20)
            if len(recent) < 3:
                return candidates

            times = [r.cycle_time_seconds for r in recent if r.cycle_time_seconds > 0]
            if not times:
                return candidates

            avg_time = sum(times) / len(times)
            slow_cycles = [r for r in recent if r.cycle_time_seconds > avg_time * 2]

            if slow_cycles:
                # Extract common agents used in slow cycles
                slow_agents: dict[str, int] = {}
                for r in slow_cycles:
                    for agent in r.agents_used:
                        slow_agents[agent] = slow_agents.get(agent, 0) + 1

                top_agent = (
                    max(slow_agents, key=slow_agents.__getitem__) if slow_agents else "unknown"
                )
                confidence = min(0.6 + len(slow_cycles) * 0.05, 0.95)

                candidates.append(
                    GoalCandidate(
                        goal_text=(
                            f"Optimize slow Nomic cycles: {len(slow_cycles)} cycles "
                            f"exceeded {avg_time:.1f}s average (most common agent: {top_agent})"
                        ),
                        confidence=confidence,
                        signal_source="slow_cycles",
                        estimated_effort=2.0,
                        estimated_impact=1.5,
                        metadata={
                            "slow_count": len(slow_cycles),
                            "avg_time": avg_time,
                            "top_slow_agent": top_agent,
                        },
                    )
                )

            # Check for high-cost cycles
            costs = [r.cost_usd for r in recent if r.cost_usd > 0]
            if costs:
                avg_cost = sum(costs) / len(costs)
                expensive = [r for r in recent if r.cost_usd > avg_cost * 3]
                if expensive:
                    candidates.append(
                        GoalCandidate(
                            goal_text=(
                                f"Reduce cycle cost: {len(expensive)} cycles exceeded "
                                f"${avg_cost:.4f} average by 3x+"
                            ),
                            confidence=min(0.6 + len(expensive) * 0.05, 0.9),
                            signal_source="slow_cycles",
                            estimated_effort=1.5,
                            estimated_impact=1.0,
                            metadata={
                                "expensive_count": len(expensive),
                                "avg_cost": avg_cost,
                            },
                        )
                    )

        except (RuntimeError, TypeError, AttributeError) as e:
            logger.debug("slow_cycle_signal_failed: %s", e)

        return candidates

    # ------------------------------------------------------------------
    # Signal: Knowledge Staleness
    # ------------------------------------------------------------------

    def _signal_knowledge_staleness(self) -> list[GoalCandidate]:
        """Query KM for stale items and propose refresh goals."""
        candidates: list[GoalCandidate] = []
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            km = get_knowledge_mound()
            if km is None:
                return candidates

            # Query for stale items (adapted for various KM APIs)
            stale_items = []
            if hasattr(km, "find_stale"):
                stale_items = km.find_stale(max_age_days=30, limit=20)
            elif hasattr(km, "search"):
                stale_items = km.search(query="stale outdated obsolete", limit=10)

            if stale_items:
                count = len(stale_items)
                candidates.append(
                    GoalCandidate(
                        goal_text=(f"Refresh {count} stale knowledge items (older than 30 days)"),
                        confidence=min(0.6 + count * 0.02, 0.9),
                        signal_source="staleness",
                        estimated_effort=1.0 + count * 0.1,
                        estimated_impact=0.8,
                        metadata={"stale_count": count},
                    )
                )

        except ImportError:
            pass
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
            logger.debug("staleness_signal_failed: %s", e)

        return candidates

    # ------------------------------------------------------------------
    # Signal: Calibration Drift
    # ------------------------------------------------------------------

    def _signal_calibration_drift(self) -> list[GoalCandidate]:
        """Check calibration monitor for drift and propose recalibration goals."""
        candidates: list[GoalCandidate] = []
        if self._calibration_monitor is None:
            return candidates

        try:
            warnings = self._calibration_monitor.detect_drift()
            if not warnings:
                return candidates

            # Group by drift type
            by_type: dict[str, list[Any]] = {}
            for w in warnings:
                by_type.setdefault(w.type, []).append(w)

            for drift_type, type_warnings in by_type.items():
                agents = list({w.agent_name for w in type_warnings})
                severity_map = {"low": 0.6, "medium": 0.8, "high": 0.95}
                max_severity = max(severity_map.get(w.severity, 0.6) for w in type_warnings)

                candidates.append(
                    GoalCandidate(
                        goal_text=(
                            f"Address calibration {drift_type} in "
                            f"{len(agents)} agent(s): {', '.join(agents[:3])}"
                        ),
                        confidence=max_severity,
                        signal_source="calibration",
                        estimated_effort=1.5,
                        estimated_impact=1.2,
                        metadata={
                            "drift_type": drift_type,
                            "agents": agents,
                            "warning_count": len(type_warnings),
                        },
                    )
                )

        except (RuntimeError, TypeError, AttributeError) as e:
            logger.debug("calibration_signal_failed: %s", e)

        return candidates

    # ------------------------------------------------------------------
    # Signal: Coverage Gaps
    # ------------------------------------------------------------------

    def _signal_coverage_gaps(self) -> list[GoalCandidate]:
        """Detect modules with low or missing test coverage.

        Reads coverage data from .coverage or coverage.json if available,
        and falls back to scanning for untested modules by checking
        whether corresponding test files exist.
        """
        candidates: list[GoalCandidate] = []

        # Strategy 1: Parse coverage.json if available
        try:
            import json as _json
            from pathlib import Path as _P

            for cov_path in [_P("coverage.json"), _P("htmlcov/status.json")]:
                if not cov_path.exists():
                    continue
                data = _json.loads(cov_path.read_text())
                totals = data.get("totals", {})
                pct = totals.get("percent_covered", None)
                if pct is not None and pct < 70:
                    candidates.append(
                        GoalCandidate(
                            goal_text=(
                                f"Improve overall test coverage (currently {pct:.1f}%, target 70%)"
                            ),
                            confidence=min(0.7 + (70 - pct) * 0.005, 0.95),
                            signal_source="coverage",
                            estimated_effort=2.0,
                            estimated_impact=1.5,
                            metadata={"coverage_pct": pct},
                        )
                    )

                # Find per-file gaps
                files = data.get("files", {})
                low_cov_files = []
                for filepath, fdata in files.items():
                    file_pct = fdata.get("summary", {}).get("percent_covered", 100)
                    if file_pct < 30 and "test" not in filepath:
                        low_cov_files.append((filepath, file_pct))

                if low_cov_files:
                    low_cov_files.sort(key=lambda x: x[1])
                    top_gaps = low_cov_files[:5]
                    file_list = ", ".join(f"{f} ({p:.0f}%)" for f, p in top_gaps)
                    candidates.append(
                        GoalCandidate(
                            goal_text=(
                                f"Add tests for {len(low_cov_files)} under-covered "
                                f"modules: {file_list}"
                            ),
                            confidence=min(0.65 + len(low_cov_files) * 0.02, 0.95),
                            signal_source="coverage",
                            estimated_effort=1.0 + len(low_cov_files) * 0.3,
                            estimated_impact=1.5,
                            metadata={
                                "low_coverage_count": len(low_cov_files),
                                "worst_files": top_gaps,
                            },
                        )
                    )
                break  # Only process the first coverage file found
        except (OSError, ValueError, KeyError, TypeError):
            pass

        # Strategy 2: Scan for production modules without test files
        if not candidates:
            try:
                from pathlib import Path as _P

                src_dir = _P("aragora")
                test_dir = _P("tests")
                if src_dir.is_dir() and test_dir.is_dir():
                    # Build set of all test filenames once (O(n) instead of O(n*m) rglob)
                    test_filenames: set[str] = set()
                    for test_file in test_dir.rglob("test_*.py"):
                        test_filenames.add(test_file.name)

                    untested = []
                    for py_file in sorted(src_dir.rglob("*.py")):
                        if py_file.name.startswith("_"):
                            continue
                        test_name = f"test_{py_file.name}"
                        if test_name not in test_filenames:
                            untested.append(str(py_file))
                            if len(untested) >= 100:
                                break  # Cap for performance

                    if len(untested) > 10:
                        candidates.append(
                            GoalCandidate(
                                goal_text=(
                                    f"Add test coverage for {len(untested)} untested modules"
                                ),
                                confidence=min(0.6 + len(untested) * 0.005, 0.85),
                                signal_source="coverage",
                                estimated_effort=2.5,
                                estimated_impact=1.3,
                                metadata={
                                    "untested_count": len(untested),
                                    "sample_files": untested[:5],
                                },
                            )
                        )
            except (OSError, ValueError):
                pass

        return candidates

    # ------------------------------------------------------------------
    # Signal: Lint Regressions
    # ------------------------------------------------------------------

    def _signal_lint_regressions(self) -> list[GoalCandidate]:
        """Run ruff and detect lint violations, proposing cleanup goals.

        Groups violations by rule code (e.g. F821, E501) and proposes
        goals for the most prevalent categories.
        """
        candidates: list[GoalCandidate] = []
        try:
            import subprocess

            result = subprocess.run(
                ["ruff", "check", "--quiet", "--output-format=concise", "."],  # fixed command
                capture_output=True,
                text=True,
                timeout=20,
                cwd=".",
            )
            if not result.stdout:
                return candidates

            lines = result.stdout.strip().splitlines()
            total_violations = len(lines)

            if total_violations == 0:
                return candidates

            # Group by rule code
            rule_counts: dict[str, int] = {}
            rule_files: dict[str, list[str]] = {}
            for line in lines:
                # Format: "path/to/file.py:42:1 E501 line too long"
                parts = line.split()
                if len(parts) >= 2:
                    rule = parts[1] if ":" in parts[0] else ""
                    if rule:
                        rule_counts[rule] = rule_counts.get(rule, 0) + 1
                        filepath = parts[0].split(":")[0]
                        rule_files.setdefault(rule, []).append(filepath)

            # Propose goals for the most prevalent rule violations
            sorted_rules = sorted(rule_counts.items(), key=lambda kv: kv[1], reverse=True)
            for rule, count in sorted_rules[:3]:
                if count < 3:
                    continue

                # Higher-severity rules get higher confidence
                severity_boost = 0.0
                if rule.startswith("F"):  # Pyflakes (undefined names, unused imports)
                    severity_boost = 0.15
                elif rule.startswith("E"):  # Style errors
                    severity_boost = 0.05

                unique_files = len(set(rule_files.get(rule, [])))
                candidates.append(
                    GoalCandidate(
                        goal_text=(
                            f"Fix {count} lint violations for rule {rule} "
                            f"across {unique_files} file(s)"
                        ),
                        confidence=min(0.6 + count * 0.02 + severity_boost, 0.95),
                        signal_source="lint",
                        estimated_effort=0.5 + count * 0.05,
                        estimated_impact=0.8 + severity_boost * 3,
                        metadata={
                            "rule": rule,
                            "violation_count": count,
                            "file_count": unique_files,
                        },
                    )
                )

            # Also propose a general lint cleanup if total is high
            if total_violations > 50 and not candidates:
                candidates.append(
                    GoalCandidate(
                        goal_text=(
                            f"Reduce lint violations from {total_violations} "
                            f"(top rules: {', '.join(r for r, _ in sorted_rules[:3])})"
                        ),
                        confidence=min(0.6 + total_violations * 0.002, 0.9),
                        signal_source="lint",
                        estimated_effort=3.0,
                        estimated_impact=1.0,
                        metadata={
                            "total_violations": total_violations,
                            "top_rules": dict(sorted_rules[:5]),
                        },
                    )
                )

        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        return candidates


__all__ = [
    "GoalCandidate",
    "GoalProposer",
]
